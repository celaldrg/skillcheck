---
name: pdf-forms
description: Fills in and flattens PDF forms from a JSON file of field values. Use when the user asks to fill, complete or flatten a PDF form.
license: MIT
metadata:
  author: celaldrg
  version: "0.1"
---

# Fill a PDF form

1. List the form's fields with `scripts/fields.py form.pdf`.
2. Write the values to `values.json`, keyed by field name.
3. Fill and flatten with `scripts/fill.py form.pdf values.json out.pdf`.

Field types and edge cases are in [the field reference](reference/fields.md).
