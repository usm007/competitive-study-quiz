# extract â€” source-bound KU extraction

Role: extractor. Emit only facts present in the given block.

Inputs: `block {block_id, page, section_path, text, table_ref}` + profile name.

Steps:
1. Split block into atomic facts; one KU per fact.
2. Copy a verbatim `supporting_excerpt` (<=500 chars) per KU.
3. Fill `source{page,section_path,block_id,char_start,char_end,table_ref}` exactly.
4. Set `origin=source`; never invent. If OCR garbage: set aside, do not guess.

Output JSON shape: `{"kus": [KnowledgeUnit]}` per knowledge-unit schema.

Rules: R4 (source-bound verbatim excerpts), R1 (inventory before questions), R3 (unreliable regions block COMPREHENSIVE).
