# NLCodec: Fast BPE Training for SentencePiece

A drop-in replacement for SentencePiece's BPE merge loop that achieves **~10× speedup** by using a max-heap with lazy deletion instead of periodic linear scans.

Enabled via the `--nlcodec_bpe` flag — everything else (sentence loading, normalization, whitespace handling, model serialization) uses SentencePiece's native code paths.

## Algorithm

SentencePiece's default BPE trainer scans an "active set" of bigrams linearly every iteration, with a full rescan every 100 steps — O(N) per merge.

NLCodec uses three data structures to achieve O(log N) per merge:

1. **Max-heap** — finding the best pair is O(log N) pop, not O(N) scan.
2. **Doubly-linked lists** — merging adjacent tokens is O(1), no array shifting.
3. **Lazy deletion ("dirty map")** — frequency decrements are accumulated in a hash map and applied on pop, avoiding O(N) heap search.

Reference: Gowda et al., [*"Many-to-English Machine Translation Tools, Data, and Pretrained Models"*](https://aclanthology.org/2021.acl-demo.37), ACL 2021.

## Usage

```bash
# Train with the fast BPE algorithm
spm_train --input=data.txt --model_prefix=model \
          --vocab_size=32000 --model_type=bpe \
          --nlcodec_bpe
```

The output `.model` and `.vocab` files are identical in format to the default path.

## Files

| File | Description |
|------|-------------|
| `bpe_model_trainer_nlcodec.h` | Data structures (LnNode, NodeArena, MaxHeap, BigramIndex, HeapDirty) and `RunFastBPEMerges()` declaration |
| `bpe_model_trainer_nlcodec.cc` | Implementation of the fast merge loop + `--nlcodec_bpe` flag definition |
| `bpe_model_trainer_nlcodec_test.cc` | 4 test cases: valid model, vocab size match, encode/decode roundtrip, vocab overlap |
| `benchmark.sh` | Self-contained benchmark script (auto-downloads CC-100 data, builds, runs) |

## Benchmark

Run the benchmark (auto-downloads multilingual CC-100 data and builds SentencePiece):

```bash
bash third_party/nlcodec/benchmark.sh              # 200k lines, 32k vocab (default)
bash third_party/nlcodec/benchmark.sh -n 1000000   # 1M lines
bash third_party/nlcodec/benchmark.sh -s            # skip encoding comparison (faster)
bash third_party/nlcodec/benchmark.sh -h            # show all options
```

### Results: 200k multilingual sentences (en, de, zh, ar, hi), 32k vocab

```
==============================================
  Default:  149.2s
  Nlcodec:  14.4s
  Speedup:  10.3x
==============================================

Vocab overlap: 31,675 / 32,000 (99.0%)
Token counts:  8,346,614 (default) vs 8,347,032 (nlcodec)
```

The two paths produce nearly identical vocabularies (99% overlap) and equivalent compression. The small differences come from tie-breaking in pair frequency ordering.