"""Databricks-focused application prompts for bulk generation"""

PROMPTS = {
    "churn-risk-dashboard": "Build a churn risk dashboard showing customers with less than 30 day login activity, declining usage trends, and support ticket volume. Calculate a risk score.",
    "revenue-by-channel": "Show daily revenue by channel (store/web/catalog) for the last 90 days with week-over-week growth rates and contribution percentages.",
    "customer-rfm-segments": "Create customer segments using RFM analysis (recency, frequency, monetary). Show 4-5 clusters with average spend, purchase frequency, and last order date.",
    "taxi-trip-metrics": "Calculate taxi trip metrics: average fare by distance bracket and time of day. Show daily trip volume and revenue trends.",
    "slow-moving-inventory": "Identify slow-moving inventory: products with more than 90 days in stock, low turnover ratio, and current warehouse capacity by location.",
    "customer-360-view": "Create a 360-degree customer view: lifetime orders, total spent, average order value, preferred categories, and payment methods used.",
    "product-pair-analysis": "Show top 10 product pairs frequently purchased together with co-occurrence rates. Calculate potential bundle revenue opportunity.",
    "revenue-forecast-quarterly": "Show revenue trends for next quarter based on historical growth rates. Display monthly comparisons and seasonal patterns.",
    "data-quality-metrics": "Monitor data quality metrics: track completeness, outliers, and value distribution changes for key fields over time.",
    "channel-conversion-comparison": "Compare conversion rates and average order value across store/web/catalog channels. Break down by customer segment.",
    "customer-churn-analysis": "Show customer churn analysis: identify customers who stopped purchasing in last 90 days, segment by last order value and ticket history.",
    "pricing-impact-analysis": "Analyze pricing impact: compare revenue at different price points by category. Show price recommendations based on historical data.",
    "supplier-scorecard": "Build supplier scorecard: on-time delivery percentage, defect rate, average lead time, and fill rate. Rank top 10 suppliers.",
    "sales-density-heatmap": "Map sales density by zip code with heatmap visualization. Show top 20 zips by revenue and compare to population density.",
    "cac-by-channel": "Calculate CAC by marketing channel (paid search, social, email, organic). Show CAC to LTV ratio and payback period in months.",
    "subscription-tier-optimization": "Identify subscription tier optimization opportunities: show high-usage users near tier limits and low-usage users in premium tiers.",
    "product-profitability": "Show product profitability: revenue minus returns percentage minus discount cost. Rank bottom 20 products by net margin.",
    "warehouse-efficiency": "Build warehouse efficiency dashboard: orders per hour, fulfillment SLA (percentage shipped within 24 hours), and capacity utilization by facility.",
    "customer-ltv-cohorts": "Calculate customer LTV by acquisition cohort: average revenue per customer at 12, 24, 36 months. Show retention curves.",
    "promotion-roi-analysis": "Measure promotion ROI: incremental revenue during promo vs cost, with 7-day post-promotion lift. Flag underperforming promotions.",
}
