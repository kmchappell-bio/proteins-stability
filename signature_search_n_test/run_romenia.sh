python ./src/main_rankings.py --projectName romenia_run_kruskal_fdr_100p_8fold --train dataset/romenia_all_samples.csv --k 3  --onlyFilter --nJobs 8 --ignoreWarnings --testSize 0.2 --fdr --fdrPvalue 0.25 --correlation --corrThreshold 0.90 --smote