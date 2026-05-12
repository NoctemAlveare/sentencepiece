#!/usr/bin/env python

# Copyright 2018 Google Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.!

import codecs
import glob
import os
import platform
import shutil
import subprocess
import sys
import sysconfig
from setuptools import Extension, setup
from setuptools.command.build_ext import build_ext as _build_ext

sys.path.append(os.path.join('.', 'test'))


def long_description():
  with codecs.open('README.md', 'r', 'utf-8') as f:
    long_description = f.read()
  return long_description


with open('src/sentencepiece/_version.py') as f:
  line = f.readline().strip()
  __version__ = line.split('=')[1].strip().strip("'")


def run_pkg_config(section, pkg_config_path=None):
  try:
    cmd = 'pkg-config sentencepiece --{}'.format(section)
    if pkg_config_path:
      cmd = 'env PKG_CONFIG_PATH={} {}'.format(pkg_config_path, cmd)
    output = subprocess.check_output(cmd, shell=True)
    if sys.version_info >= (3, 0, 0):
      output = output.decode('utf-8')
  except subprocess.CalledProcessError:
    sys.stderr.write('Failed to find sentencepiece pkg-config\n')
    sys.exit(1)
  return output.strip().split()


def is_sentencepiece_installed():
  try:
    subprocess.check_call('pkg-config sentencepiece --libs', shell=True)
    return True
  except subprocess.CalledProcessError:
    return False


def is_gil_disabled():
  return sysconfig.get_config_var('Py_GIL_DISABLED')


def find_abseil_lib(search_root):
  print('## searching abseil {}'.format(search_root))
  absl_libs = []
  ext = '.lib' if os.name == 'nt' else '.a'
  for root, dirs, files in os.walk(search_root):
    for file in files:
      if (
          file.startswith('libabsl') or file.startswith('absl')
      ) and file.endswith(ext):
        full_path = os.path.join(root, file)
        absl_libs.append(full_path)

  print('## absl_libs={}'.format(' '.join(absl_libs)))
  return absl_libs


def get_cflags_and_libs(root):
  cflags = ['-std=c++17', '-I' + os.path.join(root, 'include')]
  libs = []
  if os.path.exists(os.path.join(root, 'lib/pkgconfig/sentencepiece.pc')):
    libs = [
        os.path.join(root, 'lib/libsentencepiece.a'),
        os.path.join(root, 'lib/libsentencepiece_train.a'),
    ]
  elif os.path.exists(os.path.join(root, 'lib64/pkgconfig/sentencepiece.pc')):
    libs = [
        os.path.join(root, 'lib64/libsentencepiece.a'),
        os.path.join(root, 'lib64/libsentencepiece_train.a'),
    ]
  return cflags, libs


class build_ext_unix(_build_ext):
  """Override build_extension to run cmake."""

  def build_extension(self, ext):
    cflags, libs = get_cflags_and_libs('../build/root')

    if len(libs) == 0:
      if is_sentencepiece_installed():
        cflags = cflags + run_pkg_config('cflags')
        libs = run_pkg_config('libs')
      else:
        subprocess.check_call(['./build_bundled.sh', __version__])
        cflags, libs = get_cflags_and_libs('./build/root')

    # explictly link abseil libraries.
    libs.append('-Wl,--start-group')
    libs.extend(find_abseil_lib('./build'))
    libs.append('-Wl,--end-group')

    # Fix compile on some versions of Mac OSX
    # See: https://github.com/neulab/xnmt/issues/199
    if sys.platform == 'darwin':
      cflags.append('-mmacosx-version-min=10.9')
      # get correct SDK path by xcrun
      sdk_path = (
          subprocess.check_output(['xcrun', '--show-sdk-path']).decode().strip()
      )
      libs.extend(['-stdlib=libc++', f'-isysroot{sdk_path}'])
    else:
      if sys.platform == 'aix':
        cflags.append('-Wl,-s')
        libs.append('-Wl,-s')
      else:
        cflags.append('-Wl,-strip-all')
        libs.append('-Wl,-strip-all')
    if sys.platform == 'linux':
      libs.append('-Wl,-Bsymbolic')
    if is_gil_disabled():
      cflags.append('-DPy_GIL_DISABLED')

    libs.append('-Wl,--gc-sections')
    libs.append('-Wl,--version-script=exports.txt')

    print('## cflags={}'.format(' '.join(cflags)))
    print('## libs={}'.format(' '.join(libs)))
    ext.extra_compile_args = cflags
    ext.extra_link_args = libs
    _build_ext.build_extension(self, ext)


class build_ext_win(_build_ext):
  """Override build_extension to run cmake."""

  def build_extension(self, ext):
    # Must pre-install sentencepice into build directory.
    arch = get_win_arch()

    if not os.path.exists('..\\build_{}\\root\\lib'.format(arch)):
      # build library locally with cmake and vc++.
      cmake_arch = 'Win32'
      if arch == 'amd64':
        cmake_arch = 'x64'
      elif arch == 'arm64':
        cmake_arch = 'ARM64'

      subprocess.check_call([
          'cmake',
          'sentencepiece',
          '-A',
          cmake_arch,
          '-B',
          'build_{}'.format(arch),
          '-DSPM_ENABLE_SHARED=OFF',
          '-DSPM_ABSL_PROVIDER=module',
          '-DCMAKE_SHARED_LINKER_FLAGS="/OPT:REF /OPT:ICF /LTCG"',
          '-DCMAKE_INSTALL_PREFIX=build{}\\root'.format(arch),
      ])
      subprocess.check_call([
          'cmake',
          '--build',
          'build_{}'.format(arch),
          '--config',
          'Release',
          '--target',
          'install',
          '--parallel',
          '8',
      ])

    cflags = ['/std:c++17', '/I..\\build_{}\\root\\include'.format(arch)]
    libs = [
        '..\\build_{}\\root\\lib\\sentencepiece.lib'.format(arch),
        '..\\build_{}\\root\\lib\\sentencepiece_train.lib'.format(arch),
    ]
    libs.extend(find_abseil_lib('.\\build_{}\\third_party'.format(arch)))

    # on Windows, GIL flag is not set automatically.
    # https://docs.python.org/3/howto/free-threading-python.html
    if is_gil_disabled():
      cflags.append('/DPy_GIL_DISABLED')

    print('## cflags={}'.format(' '.join(cflags)))
    print('## libs={}'.format(' '.join(libs)))
    ext.extra_compile_args = cflags
    ext.extra_link_args = libs
    _build_ext.build_extension(self, ext)


def copy_package_data():
  """Copies shared package data"""

  package_data = os.path.join('src', 'sentencepiece', 'package_data')

  if not os.path.exists(package_data):
    os.makedirs(package_data)

  if glob.glob(os.path.join(package_data, '*.bin')):
    return

  def find_targets(roots):
    for root in roots:
      data = glob.glob(os.path.join(root, '*.bin'))
      if data:
        return data
    return []

  data = find_targets([
      '../build/root/share/sentencepiece',
      './build/root/share/sentencepiece',
      '../data',
  ])

  if not data and is_sentencepiece_installed():
    data = find_targets(run_pkg_config('datadir'))

  for filename in data:
    print('copying {} -> {}'.format(filename, package_data))
    shutil.copy(filename, package_data)


def get_win_arch():
  arch = 'win32'
  if sys.maxsize > 2**32:
    arch = 'amd64'
  if 'arm' in platform.machine().lower():
    arch = 'arm64'
  if os.getenv('PYTHON_ARCH', '') == 'ARM64':
    # Special check for arm64 under ciwheelbuild, see https://github.com/pypa/cibuildwheel/issues/1942
    arch = 'arm64'
  return arch


SENTENCEPIECE_EXT = Extension(
    'sentencepiece._sentencepiece',
    sources=['src/sentencepiece/sentencepiece_wrap.cxx'],
)


if os.name == 'nt':
  cmdclass = {'build_ext': build_ext_win}
else:
  cmdclass = {'build_ext': build_ext_unix}

if __name__ == '__main__':
  copy_package_data()
  setup(
      name='sentencepiece',
      package_dir={'': 'src'},
      py_modules=[
          'sentencepiece/__init__',
          'sentencepiece/_version',
          'sentencepiece/sentencepiece_model_pb2',
          'sentencepiece/sentencepiece_pb2',
      ],
      ext_modules=[SENTENCEPIECE_EXT],
      cmdclass=cmdclass,
  )
