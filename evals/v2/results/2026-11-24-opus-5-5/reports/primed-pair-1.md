| Arm | Model | Items | Answerable correct | False premise caught | False premise accepted | False alarms | Cited a source record | Grounded | Tool calls / item | Cost / item |
|---|---|---|---|---|---|---|---|---|---|---|
| tools, primed | claude-opus-5-5 | 175 | 100% (97–100) | 100% (90–100) | 0% | 0% (0–3) | 100% | 100% | 1.09 | $0.0104 |
| closed_book, primed | claude-opus-5-5 | 175 | 30% (23–38) | 54% (38–70) | 46% | 2% (1–6) | 97% | – | 0.0 | $0.0134 |

Rates are followed by their 95% Wilson interval, in percent.

tools, primed / claude-opus-5-5 vs closed_book, primed / claude-opus-5-5, on the 140 answerable items both ran: 98 items only the first got right, 0 only the second. Gap +70.0 points (approximate 95% interval +62.4 to +77.6); exact paired test p = 0.0.

closed_book, primed / claude-opus-5-5: 2 items were served by a fallback model; answerable accuracy without them: 30%.

| Family | tools, primed / claude-opus-5-5 | closed_book, primed / claude-opus-5-5 |
|---|---|---|
| accession_lookup | 100% | 60% |
| af_fraction | 100% | 0% |
| af_mean | 100% | 17% |
| best_xray | 100% | 83% |
| engineered_mutation | 100% | 17% |
| false_premise.absent_accession | 100% | 100% |
| false_premise.absent_feature | 100% | 100% |
| false_premise.absent_pdb | 100% | 50% |
| false_premise.author_number_as_uniprot | 100% | 0% |
| false_premise.isoform_missing | 100% | 75% |
| false_premise.no_difference | 100% | 0% |
| false_premise.obsolete_no_successor | 100% | 100% |
| false_premise.past_end | 100% | 100% |
| false_premise.unmodelled_residue | 100% | 17% |
| false_premise.wrong_wild_type | 100% | 40% |
| feature_range | 100% | 20% |
| insertion_code | 100% | 33% |
| isoform_residue | 100% | 20% |
| length | 100% | 25% |
| ligand_comp_id | 100% | 100% |
| method_resolution | 100% | 33% |
| modelled_residue | 100% | 17% |
| obsolete_replacement | 100% | 0% |
| polymer_uniprot | 100% | 12% |
| residue_at | 100% | 30% |
| structure_numbering | 100% | 25% |
| structure_residue | 100% | 17% |
| variant_lookup | 100% | 67% |
