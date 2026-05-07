def generate_summary(results: dict):
    print("\n===== INGESTION SUMMARY =====")

    total_processed = 0
    total_validated = 0
    total_normalized = 0
    total_failed = 0

    for dataset, stats in results.items():
        print(f"\nDataset: {dataset}")
        for key, value in stats.items():
            print(f"{key}: {value}")

        total_processed += stats["processed"]
        total_validated += stats["validated"]
        total_normalized += stats["normalized"]
        total_failed += stats["failed"]

    print("\n----- TOTALS -----")
    print(f"Processed: {total_processed}")
    print(f"Validated: {total_validated}")
    print(f"Normalized: {total_normalized}")
    print(f"Failed: {total_failed}")