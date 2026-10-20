# Provider plan catalog

A static, versioned catalog of model prices and documented plan allowances. The
initial adapter reads OpenCode's official Go and Go Plus documentation.

```sh
python3 -m unittest discover -s tests
python3 scripts/update.py
```

`public/catalog.json` contains source URLs, document hashes, observation and expiry
times, separate plan budgets, token prices and window fractions. Consumers must
reject expired data. Request estimates are excluded: they depend on a workload.
Promotional unlimited entries are marked explicitly and still expire.

Each model price row keeps its label as published in `name`. Tier and peak splits
(for example `Qwen3.7 Plus (> 256K tokens)` or `DeepSeek V4.1 Flash (Peak)`) are
also split into `base_name` and `variant`, so one model can have several price
rows; `variant` is `null` when the label has no split. `monthly_allowance_usd` is
the allowance in effect now. During a limited-time promotion the page strikes
through the standard allowance, which is kept in `base_monthly_allowance_usd`,
and `limited_time_multiplier` holds the promoted multiplier. Both are `null`
otherwise. The parser checks that the promoted allowance equals the standard
allowance times the multiplier, and fails on any other promotion label.

CI refreshes the public documentation every six hours, validates the result, and
builds a static image. Unsupported source layouts fail without replacing the last
catalog. Add new providers as explicit adapters with fixture tests.

The image contains static public files and an unprivileged web server. It has no
account connector, provider credential, private API token or account database.
Deploy it independently of any service that handles private account usage.
