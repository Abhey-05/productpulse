# ProductPulse — Pipeline Build Log

Database: /Users/abheygarg05/Desktop/sql project/productpulse/data/processed/productpulse.duckdb

Raw source rows: Oct=42,448,764, Nov=67,501,979, Total=109,950,743

### 1. fact_events
- SKIPPED (already exists, 109,820,004 rows) — resuming pipeline

### 2. dim_product (canonical attributes per product)
- SKIPPED (table `dim_product` already exists, 206,876 rows) — resuming pipeline

### 3. dim_category
- SKIPPED (table `dim_category` already exists, 129 rows) — resuming pipeline

### 4. session_summary
- SKIPPED (already exists, 23,020,473 rows) — resuming pipeline

### 5a. session_product_funnel — Oct
- SKIPPED (table already exists, 69,798,061 rows so far) — resuming pipeline

### 5b.1 session_product_funnel — Nov day 1 (2019-11-01)
- SKIPPED (already has 937,422 rows) — resuming pipeline

### 5b.2 session_product_funnel — Nov day 2 (2019-11-02)
- SKIPPED (already has 1,009,806 rows) — resuming pipeline

### 5b.3 session_product_funnel — Nov day 3 (2019-11-03)
- SKIPPED (already has 1,012,990 rows) — resuming pipeline

### 5b.4 session_product_funnel — Nov day 4 (2019-11-04)
- SKIPPED (already has 1,170,661 rows) — resuming pipeline

### 5b.5 session_product_funnel — Nov day 5 (2019-11-05)
- SKIPPED (already has 1,121,563 rows) — resuming pipeline

### 5b.6 session_product_funnel — Nov day 6 (2019-11-06)
- SKIPPED (already has 1,102,265 rows) — resuming pipeline

### 5b.7 session_product_funnel — Nov day 7 (2019-11-07)
- SKIPPED (already has 1,179,600 rows) — resuming pipeline

### 5b.8 session_product_funnel — Nov day 8 (2019-11-08)
- SKIPPED (already has 1,218,785 rows) — resuming pipeline

### 5b.9 session_product_funnel — Nov day 9 (2019-11-09)
- SKIPPED (already has 1,202,279 rows) — resuming pipeline

### 5b.10 session_product_funnel — Nov day 10 (2019-11-10)
- SKIPPED (already has 1,238,925 rows) — resuming pipeline

### 5b.11 session_product_funnel — Nov day 11 (2019-11-11)
- SKIPPED (already has 1,295,675 rows) — resuming pipeline

### 5b.12 session_product_funnel — Nov day 12 (2019-11-12)
- SKIPPED (already has 1,288,384 rows) — resuming pipeline

### 5b.13 session_product_funnel — Nov day 13 (2019-11-13)
- SKIPPED (already has 1,296,222 rows) — resuming pipeline

### 5b.14 session_product_funnel — Nov day 14 (2019-11-14)
- SKIPPED (already has 1,848,359 rows) — resuming pipeline

### 5b.15 session_product_funnel — Nov day 15 (2019-11-15)
- SKIPPED (already has 3,512,000 rows) — resuming pipeline

### 5b.16 session_product_funnel — Nov day 16 (2019-11-16)
- SKIPPED (already has 3,884,167 rows) — resuming pipeline

### 5b.17 session_product_funnel — Nov day 17 (2019-11-17)
- SKIPPED (already has 3,653,292 rows) — resuming pipeline

### 5b.18 session_product_funnel — Nov day 18 (2019-11-18)
- SKIPPED (already has 1,304,053 rows) — resuming pipeline

### 5b.19 session_product_funnel — Nov day 19 (2019-11-19)
- SKIPPED (already has 1,119,447 rows) — resuming pipeline

### 5b.20 session_product_funnel — Nov day 20 (2019-11-20)
- SKIPPED (already has 1,098,270 rows) — resuming pipeline

### 5b.21 session_product_funnel — Nov day 21 (2019-11-21)
- SKIPPED (already has 1,077,273 rows) — resuming pipeline

### 5b.22 session_product_funnel — Nov day 22 (2019-11-22)
- SKIPPED (already has 1,001,791 rows) — resuming pipeline

### 5b.23 session_product_funnel — Nov day 23 (2019-11-23)
- SKIPPED (already has 996,520 rows) — resuming pipeline

### 5b.24 session_product_funnel — Nov day 24 (2019-11-24)
- SKIPPED (already has 1,006,693 rows) — resuming pipeline

### 5b.25 session_product_funnel — Nov day 25 (2019-11-25)
- SKIPPED (already has 1,013,354 rows) — resuming pipeline

### 5b.26 session_product_funnel — Nov day 26 (2019-11-26)
- SKIPPED (already has 1,059,430 rows) — resuming pipeline

### 5b.27 session_product_funnel — Nov day 27 (2019-11-27)
- SKIPPED (already has 1,057,664 rows) — resuming pipeline

### 5b.28 session_product_funnel — Nov day 28 (2019-11-28)
- SKIPPED (already has 1,056,924 rows) — resuming pipeline

### 5b.29 session_product_funnel — Nov day 29 (2019-11-29)
- SKIPPED (already has 1,156,360 rows) — resuming pipeline

### 5b.30 session_product_funnel — Nov day 30 (2019-11-30)
- SKIPPED (already has 1,091,945 rows) — resuming pipeline

- session_product_funnel final row count: 69,798,061
- (session,product) pairs purchased with no prior cart event: 529,679
  [disk check @ 6. agg_daily_funnel] 20.74 GB free

### 6. agg_daily_funnel
- rows in `agg_daily_funnel`: 61
- elapsed: 44.6s
- disk free after: 20.74 GB
  [disk check @ 7. agg_product_metrics] 20.74 GB free

### 7. agg_product_metrics
- rows in `agg_product_metrics`: 206,876
- elapsed: 4.1s
- disk free after: 20.72 GB
  [disk check @ 8. agg_category_metrics] 20.72 GB free

### 8. agg_category_metrics
- rows in `agg_category_metrics`: 129
- elapsed: 5.2s
- disk free after: 20.77 GB
  [disk check @ 9. agg_brand_metrics] 20.77 GB free

### 9. agg_brand_metrics
- rows in `agg_brand_metrics`: 4,303
- elapsed: 3.8s
- disk free after: 20.76 GB
  [disk check @ 10. agg_price_band_metrics] 20.76 GB free

### 10. agg_price_band_metrics
- rows in `agg_price_band_metrics`: 8
- elapsed: 2.6s
- disk free after: 20.77 GB
  [disk check @ 11. agg_user_metrics] 20.77 GB free

### 11. agg_user_metrics
- rows in `agg_user_metrics`: 5,316,649
- elapsed: 36.8s
- disk free after: 19.71 GB

### Creating indexes
- idx_fact_events_date: 0.0s
- idx_fact_events_product: 42.5s
- idx_spf_category: 15.1s
- idx_spf_brand: 18.4s
- elapsed: 76.0s

---
**Total pipeline runtime: 9.7 minutes**