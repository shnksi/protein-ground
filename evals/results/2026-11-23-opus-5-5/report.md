| Arm | Model | Items | Answerable correct | False premise caught | False premise accepted | False alarms | Cited a source record | Grounded | Tool calls / item | Cost / item |
|---|---|---|---|---|---|---|---|---|---|---|
| tools | claude-opus-5-5 | 68 | 100% (94–100) | 100% (77–100) | 0% | 0% (0–6) | 100% | 100% | 1.03 | $0.0087 |
| closed_book | claude-opus-5-5 | 68 | 78% (66–87) | 100% (77–100) | 0% | 2% (0–10) | 96% | – | 0.0 | $0.0103 |

Rates are followed by their 95% Wilson interval, in percent.

tools / claude-opus-5-5 vs closed_book / claude-opus-5-5, on the 55 answerable items both ran: 12 items only the first got right, 0 only the second. Gap +21.8 points (approximate 95% interval +10.9 to +32.7); exact paired test p = 0.0005.

| Family | tools / claude-opus-5-5 | closed_book / claude-opus-5-5 |
|---|---|---|
| accession_lookup | 100% | 100% |
| af_fraction | 100% | 0% |
| af_mean | 100% | 33% |
| best_xray | 100% | 25% |
| false_premise | 100% | 100% |
| feature_range | 100% | 88% |
| length | 100% | 100% |
| ligand_comp_id | 100% | 100% |
| method_resolution | 100% | 100% |
| polymer_uniprot | 100% | 100% |
| residue_at | 100% | 100% |
