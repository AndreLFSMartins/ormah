# 12 — disposition of #193 (edge `reason` lost in markdown round-trips)

Type: grilling

## Question

[#193](https://github.com/r-spade/ormah/issues/193): edge `reason` never survives markdown
round-trips — all 4,645 edges `NULL`. Touches the same serialization surface #223 will modify
(markdown ↔ index lifecycle state). Disposition only: bundle with #223's serialization work,
sequence separately, or defer? Who owns it?
