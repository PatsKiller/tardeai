# CIO / Hermes / Research Intelligence links

The investment-office CIO surface and the engineering-oriented Control Plane
remain separate products. Their evidence is connected by explicit links.

## Operator paths

- A CIO decision with a symbol links to its direct `decision_id` lineage and to
  Research Intelligence filtered to that symbol.
- Research Intelligence accepts `symbol`/`q` query context and links back to
  CIO Research. Hermes-originated items also link to Hermes Provenance.
- Hermes exposes CIO Research and Research Intelligence entry points from its
  operator header.

All links are router-relative under the `/v3` basename. No page claims that a
link proves the underlying artifact was used in judgment; provenance state is
rendered by the CIO evidence contract.
