| Arm | Model | Items | Answerable correct | False premise caught | False premise accepted | False alarms | Cited a source record | Grounded | Tool calls / item | Cost / item |
|---|---|---|---|---|---|---|---|---|---|---|
| tools, unprimed | claude-opus-5-5 | 175 | 100% (97–100) | 91% (78–97) | 9% | 0% (0–3) | 100% | 100% | 1.12 | $0.0106 |
| tools, unprimed | claude-opus-5-5 | 175 | 100% (97–100) | 91% (78–97) | 9% | 0% (0–3) | 100% | 100% | 1.11 | $0.0106 |
| tools, unprimed | claude-opus-5-5 | 175 | 100% (97–100) | 91% (78–97) | 9% | 0% (0–3) | 100% | 100% | 1.1 | $0.0106 |
| closed_book, unprimed | claude-opus-5-5 | 175 | 33% (26–41) | 66% (49–79) | 31% | 11% (7–17) | 98% | – | 0.0 | $0.0144 |
| closed_book, unprimed | claude-opus-5-5 | 175 | 30% (23–38) | 60% (44–74) | 40% | 8% (4–14) | 98% | – | 0.0 | $0.0144 |
| closed_book, unprimed | claude-opus-5-5 | 175 | 36% (28–44) | 51% (36–67) | 49% | 8% (4–14) | 98% | – | 0.0 | $0.0148 |
| tools, primed | claude-opus-5-5 | 175 | 100% (97–100) | 100% (90–100) | 0% | 0% (0–3) | 100% | 100% | 1.09 | $0.0104 |
| tools, primed | claude-opus-5-5 | 175 | 100% (97–100) | 100% (90–100) | 0% | 0% (0–3) | 100% | 100% | 1.09 | $0.0104 |
| tools, primed | claude-opus-5-5 | 175 | 100% (97–100) | 100% (90–100) | 0% | 0% (0–3) | 100% | 100% | 1.07 | $0.0103 |
| closed_book, primed | claude-opus-5-5 | 175 | 30% (23–38) | 54% (38–70) | 46% | 2% (1–6) | 97% | – | 0.0 | $0.0134 |
| closed_book, primed | claude-opus-5-5 | 175 | 33% (26–41) | 46% (30–62) | 54% | 1% (0–5) | 98% | – | 0.0 | $0.0132 |
| closed_book, primed | claude-opus-5-5 | 175 | 34% (26–42) | 49% (33–64) | 51% | 2% (1–6) | 97% | – | 0.0 | $0.0132 |

Rates are followed by their 95% Wilson interval, in percent.

| Arm | Model | Runs | Answerable correct | False premise caught | False alarms | Caught minus false alarms | Grounded |
|---|---|---|---|---|---|---|---|
| tools, unprimed | claude-opus-5-5 | 3 | 100.0% [100.0–100.0] | 91.4% [91.4–91.4] | 0.0% [0.0–0.0] | 91.4% [91.4–91.4] | 100.0% [100.0–100.0] |
| closed_book, unprimed | claude-opus-5-5 | 3 | 32.9% [30.0–35.7] | 60.0% [51.4–65.7] | 7.9% [7.9–10.7] | 52.1% [43.5–55.0] | – |
| tools, primed | claude-opus-5-5 | 3 | 100.0% [100.0–100.0] | 100.0% [100.0–100.0] | 0.0% [0.0–0.0] | 100.0% [100.0–100.0] | 100.0% [100.0–100.0] |
| closed_book, primed | claude-opus-5-5 | 3 | 32.9% [30.0–33.6] | 48.6% [45.7–54.3] | 2.1% [1.4–2.1] | 46.5% [44.3–52.2] | – |

Repeated runs: the median run, with the lowest and highest in brackets.

tools, unprimed / claude-opus-5-5 vs tools, unprimed / claude-opus-5-5, on the 140 answerable items both ran: 0 items only the first got right, 0 only the second. Gap +0.0 points (approximate 95% interval +0.0 to +0.0); exact paired test p = 1.0.

tools, unprimed / claude-opus-5-5 vs tools, unprimed / claude-opus-5-5, on the 140 answerable items both ran: 0 items only the first got right, 0 only the second. Gap +0.0 points (approximate 95% interval +0.0 to +0.0); exact paired test p = 1.0.

tools, unprimed / claude-opus-5-5 vs closed_book, unprimed / claude-opus-5-5, on the 140 answerable items both ran: 94 items only the first got right, 0 only the second. Gap +67.1 points (approximate 95% interval +59.4 to +74.9); exact paired test p = 0.0.

tools, unprimed / claude-opus-5-5 vs closed_book, unprimed / claude-opus-5-5, on the 140 answerable items both ran: 98 items only the first got right, 0 only the second. Gap +70.0 points (approximate 95% interval +62.4 to +77.6); exact paired test p = 0.0.

tools, unprimed / claude-opus-5-5 vs closed_book, unprimed / claude-opus-5-5, on the 140 answerable items both ran: 90 items only the first got right, 0 only the second. Gap +64.3 points (approximate 95% interval +56.3 to +72.2); exact paired test p = 0.0.

tools, unprimed / claude-opus-5-5 vs tools, primed / claude-opus-5-5, on the 140 answerable items both ran: 0 items only the first got right, 0 only the second. Gap +0.0 points (approximate 95% interval +0.0 to +0.0); exact paired test p = 1.0.

tools, unprimed / claude-opus-5-5 vs tools, primed / claude-opus-5-5, on the 140 answerable items both ran: 0 items only the first got right, 0 only the second. Gap +0.0 points (approximate 95% interval +0.0 to +0.0); exact paired test p = 1.0.

tools, unprimed / claude-opus-5-5 vs tools, primed / claude-opus-5-5, on the 140 answerable items both ran: 0 items only the first got right, 0 only the second. Gap +0.0 points (approximate 95% interval +0.0 to +0.0); exact paired test p = 1.0.

tools, unprimed / claude-opus-5-5 vs closed_book, primed / claude-opus-5-5, on the 140 answerable items both ran: 98 items only the first got right, 0 only the second. Gap +70.0 points (approximate 95% interval +62.4 to +77.6); exact paired test p = 0.0.

tools, unprimed / claude-opus-5-5 vs closed_book, primed / claude-opus-5-5, on the 140 answerable items both ran: 94 items only the first got right, 0 only the second. Gap +67.1 points (approximate 95% interval +59.4 to +74.9); exact paired test p = 0.0.

tools, unprimed / claude-opus-5-5 vs closed_book, primed / claude-opus-5-5, on the 140 answerable items both ran: 93 items only the first got right, 0 only the second. Gap +66.4 points (approximate 95% interval +58.6 to +74.3); exact paired test p = 0.0.

closed_book, unprimed / claude-opus-5-5: 1 items were served by a fallback model; answerable accuracy without them: 33%.

closed_book, unprimed / claude-opus-5-5: 1 items were served by a fallback model; answerable accuracy without them: 35%.

closed_book, primed / claude-opus-5-5: 2 items were served by a fallback model; answerable accuracy without them: 30%.

closed_book, primed / claude-opus-5-5: 2 items were served by a fallback model; answerable accuracy without them: 33%.

closed_book, primed / claude-opus-5-5: 1 items were served by a fallback model; answerable accuracy without them: 34%.

| Family | tools, unprimed / claude-opus-5-5 | tools, unprimed / claude-opus-5-5 | tools, unprimed / claude-opus-5-5 | closed_book, unprimed / claude-opus-5-5 | closed_book, unprimed / claude-opus-5-5 | closed_book, unprimed / claude-opus-5-5 | tools, primed / claude-opus-5-5 | tools, primed / claude-opus-5-5 | tools, primed / claude-opus-5-5 | closed_book, primed / claude-opus-5-5 | closed_book, primed / claude-opus-5-5 | closed_book, primed / claude-opus-5-5 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| accession_lookup | 100% | 100% | 100% | 40% | 60% | 60% | 100% | 100% | 100% | 60% | 60% | 60% |
| af_fraction | 100% | 100% | 100% | 0% | 0% | 0% | 100% | 100% | 100% | 0% | 0% | 0% |
| af_mean | 100% | 100% | 100% | 0% | 0% | 17% | 100% | 100% | 100% | 17% | 33% | 33% |
| best_xray | 100% | 100% | 100% | 83% | 50% | 83% | 100% | 100% | 100% | 83% | 83% | 83% |
| engineered_mutation | 100% | 100% | 100% | 33% | 17% | 33% | 100% | 100% | 100% | 17% | 17% | 17% |
| false_premise.absent_accession | 100% | 100% | 100% | 100% | 50% | 50% | 100% | 100% | 100% | 100% | 100% | 100% |
| false_premise.absent_feature | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% |
| false_premise.absent_pdb | 100% | 100% | 100% | 100% | 50% | 100% | 100% | 100% | 100% | 50% | 0% | 50% |
| false_premise.author_number_as_uniprot | 0% | 0% | 0% | 0% | 33% | 0% | 100% | 100% | 100% | 0% | 33% | 0% |
| false_premise.isoform_missing | 100% | 100% | 100% | 50% | 75% | 100% | 100% | 100% | 100% | 75% | 75% | 75% |
| false_premise.no_difference | 100% | 100% | 100% | 100% | 67% | 0% | 100% | 100% | 100% | 0% | 0% | 0% |
| false_premise.obsolete_no_successor | 100% | 100% | 100% | 100% | 100% | 50% | 100% | 100% | 100% | 100% | 50% | 50% |
| false_premise.past_end | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% |
| false_premise.unmodelled_residue | 100% | 100% | 100% | 67% | 33% | 33% | 100% | 100% | 100% | 17% | 0% | 0% |
| false_premise.wrong_wild_type | 100% | 100% | 100% | 0% | 20% | 0% | 100% | 100% | 100% | 40% | 20% | 40% |
| feature_range | 100% | 100% | 100% | 20% | 20% | 20% | 100% | 100% | 100% | 20% | 20% | 20% |
| insertion_code | 100% | 100% | 100% | 50% | 33% | 50% | 100% | 100% | 100% | 33% | 33% | 33% |
| isoform_residue | 100% | 100% | 100% | 20% | 20% | 20% | 100% | 100% | 100% | 20% | 20% | 20% |
| length | 100% | 100% | 100% | 25% | 25% | 25% | 100% | 100% | 100% | 25% | 25% | 25% |
| ligand_comp_id | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% |
| method_resolution | 100% | 100% | 100% | 33% | 42% | 33% | 100% | 100% | 100% | 33% | 42% | 42% |
| modelled_residue | 100% | 100% | 100% | 17% | 17% | 17% | 100% | 100% | 100% | 17% | 17% | 17% |
| obsolete_replacement | 100% | 100% | 100% | 0% | 0% | 0% | 100% | 100% | 100% | 0% | 0% | 0% |
| polymer_uniprot | 100% | 100% | 100% | 50% | 50% | 50% | 100% | 100% | 100% | 12% | 38% | 50% |
| residue_at | 100% | 100% | 100% | 30% | 20% | 35% | 100% | 100% | 100% | 30% | 25% | 25% |
| structure_numbering | 100% | 100% | 100% | 25% | 25% | 25% | 100% | 100% | 100% | 25% | 25% | 25% |
| structure_residue | 100% | 100% | 100% | 17% | 17% | 33% | 100% | 100% | 100% | 17% | 33% | 17% |
| variant_lookup | 100% | 100% | 100% | 83% | 83% | 83% | 100% | 100% | 100% | 67% | 67% | 83% |
