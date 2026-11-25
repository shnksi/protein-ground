| Arm | Model | Items | Answerable correct | False premise caught | False premise accepted | False alarms | Cited a source record | Grounded | Tool calls / item | Cost / item |
|---|---|---|---|---|---|---|---|---|---|---|
| tools, unprimed | claude-opus-5-5 | 175 | 100% (97–100) | 91% (78–97) | 9% | 0% (0–3) | 100% | 100% | 1.11 | $0.0106 |
| closed_book, unprimed | claude-opus-5-5 | 175 | 30% (23–38) | 60% (44–74) | 40% | 8% (4–14) | 98% | – | 0.0 | $0.0144 |
| tools, primed | claude-opus-5-5 | 175 | 100% (97–100) | 100% (90–100) | 0% | 0% (0–3) | 100% | 100% | 1.09 | $0.0104 |

Rates are followed by their 95% Wilson interval, in percent.

tools, unprimed / claude-opus-5-5 vs closed_book, unprimed / claude-opus-5-5, on the 140 answerable items both ran: 98 items only the first got right, 0 only the second. Gap +70.0 points (approximate 95% interval +62.4 to +77.6); exact paired test p = 0.0.

tools, unprimed / claude-opus-5-5 vs tools, primed / claude-opus-5-5, on the 140 answerable items both ran: 0 items only the first got right, 0 only the second. Gap +0.0 points (approximate 95% interval +0.0 to +0.0); exact paired test p = 1.0.

| Family | tools, unprimed / claude-opus-5-5 | closed_book, unprimed / claude-opus-5-5 | tools, primed / claude-opus-5-5 |
|---|---|---|---|
| accession_lookup | 100% | 60% | 100% |
| af_fraction | 100% | 0% | 100% |
| af_mean | 100% | 0% | 100% |
| best_xray | 100% | 50% | 100% |
| engineered_mutation | 100% | 17% | 100% |
| false_premise.absent_accession | 100% | 50% | 100% |
| false_premise.absent_feature | 100% | 100% | 100% |
| false_premise.absent_pdb | 100% | 50% | 100% |
| false_premise.author_number_as_uniprot | 0% | 33% | 100% |
| false_premise.isoform_missing | 100% | 75% | 100% |
| false_premise.no_difference | 100% | 67% | 100% |
| false_premise.obsolete_no_successor | 100% | 100% | 100% |
| false_premise.past_end | 100% | 100% | 100% |
| false_premise.unmodelled_residue | 100% | 33% | 100% |
| false_premise.wrong_wild_type | 100% | 20% | 100% |
| feature_range | 100% | 20% | 100% |
| insertion_code | 100% | 33% | 100% |
| isoform_residue | 100% | 20% | 100% |
| length | 100% | 25% | 100% |
| ligand_comp_id | 100% | 100% | 100% |
| method_resolution | 100% | 42% | 100% |
| modelled_residue | 100% | 17% | 100% |
| obsolete_replacement | 100% | 0% | 100% |
| polymer_uniprot | 100% | 50% | 100% |
| residue_at | 100% | 20% | 100% |
| structure_numbering | 100% | 25% | 100% |
| structure_residue | 100% | 17% | 100% |
| variant_lookup | 100% | 83% | 100% |
