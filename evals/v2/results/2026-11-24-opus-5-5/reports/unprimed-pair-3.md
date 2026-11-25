| Arm | Model | Items | Answerable correct | False premise caught | False premise accepted | False alarms | Cited a source record | Grounded | Tool calls / item | Cost / item |
|---|---|---|---|---|---|---|---|---|---|---|
| tools, unprimed | claude-opus-5-5 | 175 | 100% (97–100) | 91% (78–97) | 9% | 0% (0–3) | 100% | 100% | 1.1 | $0.0106 |
| closed_book, unprimed | claude-opus-5-5 | 175 | 36% (28–44) | 51% (36–67) | 49% | 8% (4–14) | 98% | – | 0.0 | $0.0148 |
| tools, primed | claude-opus-5-5 | 175 | 100% (97–100) | 100% (90–100) | 0% | 0% (0–3) | 100% | 100% | 1.07 | $0.0103 |

Rates are followed by their 95% Wilson interval, in percent.

tools, unprimed / claude-opus-5-5 vs closed_book, unprimed / claude-opus-5-5, on the 140 answerable items both ran: 90 items only the first got right, 0 only the second. Gap +64.3 points (approximate 95% interval +56.3 to +72.2); exact paired test p = 0.0.

tools, unprimed / claude-opus-5-5 vs tools, primed / claude-opus-5-5, on the 140 answerable items both ran: 0 items only the first got right, 0 only the second. Gap +0.0 points (approximate 95% interval +0.0 to +0.0); exact paired test p = 1.0.

closed_book, unprimed / claude-opus-5-5: 1 items were served by a fallback model; answerable accuracy without them: 35%.

| Family | tools, unprimed / claude-opus-5-5 | closed_book, unprimed / claude-opus-5-5 | tools, primed / claude-opus-5-5 |
|---|---|---|---|
| accession_lookup | 100% | 60% | 100% |
| af_fraction | 100% | 0% | 100% |
| af_mean | 100% | 17% | 100% |
| best_xray | 100% | 83% | 100% |
| engineered_mutation | 100% | 33% | 100% |
| false_premise.absent_accession | 100% | 50% | 100% |
| false_premise.absent_feature | 100% | 100% | 100% |
| false_premise.absent_pdb | 100% | 100% | 100% |
| false_premise.author_number_as_uniprot | 0% | 0% | 100% |
| false_premise.isoform_missing | 100% | 100% | 100% |
| false_premise.no_difference | 100% | 0% | 100% |
| false_premise.obsolete_no_successor | 100% | 50% | 100% |
| false_premise.past_end | 100% | 100% | 100% |
| false_premise.unmodelled_residue | 100% | 33% | 100% |
| false_premise.wrong_wild_type | 100% | 0% | 100% |
| feature_range | 100% | 20% | 100% |
| insertion_code | 100% | 50% | 100% |
| isoform_residue | 100% | 20% | 100% |
| length | 100% | 25% | 100% |
| ligand_comp_id | 100% | 100% | 100% |
| method_resolution | 100% | 33% | 100% |
| modelled_residue | 100% | 17% | 100% |
| obsolete_replacement | 100% | 0% | 100% |
| polymer_uniprot | 100% | 50% | 100% |
| residue_at | 100% | 35% | 100% |
| structure_numbering | 100% | 25% | 100% |
| structure_residue | 100% | 33% | 100% |
| variant_lookup | 100% | 83% | 100% |
