# Reckitt Brand Planning Agent POC

**Client:** Reckitt Benckiser
**Scope:** Surface Care category, Lysol brand, US market
**Duration:** 6 weeks

---

## Data Sources

### 1. Finance Data
Internal P&L extract with fiscal period granularity.

| Metric | Description |
|--------|-------------|
| gross_sales_act | Gross sales actual |
| net_revenue_act | Net revenue actual |
| gross_margin_act | Gross margin actual |

Dimensions: power_brand_name, category_description, sub_category_description, segment_description, country, fiscal_period

### 2. Panel Data
Household panel metrics for penetration and purchase behavior.

| Metric | Description |
|--------|-------------|
| % Household Penetration | % of households purchasing |
| Repeat Rate | % of buyers who repurchase |
| Buy Rate | Units per buyer |

Dimensions: Parent_Brand, Category, Brand, Channel/Banner, Quarter

### 3. Nielsen xAoC
Syndicated scanner data in star schema format.

**Fact metrics:** value_sales, unit_sales, volume_sales, acv_distribution, tdp, price_per_unit, promo metrics, baseline metrics

**Dimensions:** brand, sub_brand, manufacturer, category, sub_category, segment, channel, retailer, week_ending_date

---

## Tools

| Tool | Purpose |
|------|---------|
| Market Share Analysis | Track share trends vs competitors by segment/retailer |
| Revenue Drivers | Variance analysis for net_revenue and gross_margin |
| Trend | Time series visualization |
| Dimensional Breakout | Contribution analysis by dimension |

---

## Architecture

- Finance data: Single flat table
- Panel data: Single flat table
- Nielsen: Star schema (Fact + Product/Market/Period dimensions)
