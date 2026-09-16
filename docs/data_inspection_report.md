# ProductPulse — Raw Data Inspection Report

Generated from files:
- /Users/abheygarg05/Desktop/sql project/productpulse/data/raw/2019-Oct.csv
- /Users/abheygarg05/Desktop/sql project/productpulse/data/raw/2019-Nov.csv

## 1. Row counts
- 2019-Oct.csv rows: 42,448,764
- 2019-Nov.csv rows: 67,501,979
- Combined rows: 109,950,743

## 2. Schema (inferred by DuckDB)
| column_name   | column_type   | null   | key   | default   | extra   |
|:--------------|:--------------|:-------|:------|:----------|:--------|
| event_time    | TIMESTAMP     | YES    |       |           |         |
| event_type    | VARCHAR       | YES    |       |           |         |
| product_id    | BIGINT        | YES    |       |           |         |
| category_id   | BIGINT        | YES    |       |           |         |
| category_code | VARCHAR       | YES    |       |           |         |
| brand         | VARCHAR       | YES    |       |           |         |
| price         | DOUBLE        | YES    |       |           |         |
| user_id       | BIGINT        | YES    |       |           |         |
| user_session  | VARCHAR       | YES    |       |           |         |

## 3. Date range
- Min event_time: 2019-10-01 00:00:00
- Max event_time: 2019-11-30 23:59:59

## 4. Event type breakdown
| event_type   |         n |    pct |
|:-------------|----------:|-------:|
| view         | 104335509 | 94.893 |
| cart         |   3955446 |  3.597 |
| purchase     |   1659788 |  1.51  |

## 5. Cardinality (distinct counts)
|   distinct_users |   distinct_sessions |   distinct_products |   distinct_category_ids |   distinct_category_codes |   distinct_brands |
|-----------------:|--------------------:|--------------------:|------------------------:|--------------------------:|------------------:|
|          5316649 |            23016650 |              206876 |                     691 |                       129 |              4303 |

## 6. Missing value rates (%)
|                        |       0 |
|:-----------------------|--------:|
| event_time_null_pct    |  0      |
| event_type_null_pct    |  0      |
| product_id_null_pct    |  0      |
| category_id_null_pct   |  0      |
| category_code_null_pct | 32.2088 |
| brand_null_pct         | 13.9437 |
| price_null_pct         |  0      |
| user_id_null_pct       |  0      |
| user_session_null_pct  |  0      |

## 7. Exact duplicate rows
|   total_rows |   duplicate_rows |
|-------------:|-----------------:|
|    109950743 |           130739 |

## 8. Price sanity check
|   min_price |   max_price |   avg_price |   negative_price_rows |   zero_price_rows |
|------------:|------------:|------------:|----------------------:|------------------:|
|           0 |     2574.07 |     291.635 |                     0 |            256761 |

## 9. Distinct event_type values
| event_type   |
|:-------------|
| view         |
| cart         |
| purchase     |

## 10. Sample category_code values (non-null)
| category_code                       |
|:------------------------------------|
| appliances.environment.water_heater |
| apparel.shoes.keds                  |
| appliances.kitchen.microwave        |
| electronics.audio.headphone         |
| computers.peripherals.monitor       |
| construction.tools.drill            |
| furniture.bathroom.toilet           |
| appliances.kitchen.blender          |
| construction.tools.welding          |
| auto.accessories.videoregister      |
| furniture.living_room.cabinet       |
| accessories.bag                     |
| computers.components.motherboard    |
| appliances.kitchen.oven             |
| construction.tools.generator        |
| sport.bicycle                       |
| furniture.kitchen.chair             |
| kids.fmcg.diapers                   |
| computers.ebooks                    |
| furniture.bedroom.pillow            |

## 11. category_code coverage
|   total_rows |   null_category_code |   null_brand |
|-------------:|---------------------:|-------------:|
|  1.09951e+08 |          3.54138e+07 |  1.53312e+07 |

## 12. Session integrity check (does user_session map 1:1 to user_id?)
|   sessions_with_multiple_users |
|-------------------------------:|
|                            940 |

## 13. Distinct dates covered & any gaps
- Number of distinct calendar days: 61
- First day: 2019-10-01 00:00:00, Last day: 2019-11-30 00:00:00
- Min events/day: 1,127,303, Max events/day: 6,502,957

---
Inspection completed in 633.8s