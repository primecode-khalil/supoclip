# Product design and source research

The agreed approach is to fork SupoClip and implement the missing recording/archive/local-processing capabilities through its existing architecture, retaining polished vertical clips, captions, editing and publishing.

The [combined product design](../../research/combined-product-design.md) and its linked feature inventories record the detailed source-backed architecture, feature preservation requirements and explicit missing work.

The first implementation slice is [recording foundation](2026-11-16-recording-foundation-design.md); it adds a durable registry/ledger and does not start a recorder. Later slices implement capture supervision, finalized media, archives, ASR adapters, near-live workflows and additional publishing capabilities.
