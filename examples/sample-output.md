```text
examples/bad-mixed.yaml:3: indentation of 3 spaces is not a multiple of the file's indent width of 2 spaces
examples/bad-mixed.yaml:5: indentation of 3 spaces is not a multiple of the file's indent width of 2 spaces
examples/bad-mixed.yaml:6: indentation of 5 spaces is not a multiple of the file's indent width of 2 spaces
examples/bad-tabs.yaml:2: tab character used for indentation (YAML forbids tabs for indentation)
examples/bad-tabs.yaml:3: tab character used for indentation (YAML forbids tabs for indentation)
examples/configs/app.yaml:3: indentation of 3 spaces is not a multiple of the file's indent width of 2 spaces
Checked 5 file(s), 6 problem(s) in 3 file(s).
```

Output of `sh examples/run-example.sh` — the checker on the whole
`examples/` folder. It exits 1, because the examples contain files
with bad indentation on purpose; the script itself exits 0.
