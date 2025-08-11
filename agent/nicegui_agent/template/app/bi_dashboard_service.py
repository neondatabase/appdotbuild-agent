"""
BI Dashboard Service for Bakehouse Analytics 🥐📊

This service provides comprehensive analytics data for the go-to-market dashboard,
fetching real-time sales statistics from Databricks and processing them for UI display.
"""

from logging import getLogger
from typing import Dict, List, Any, Optional

from app.models import (
    SalesKPIs,
    DailySalesRevenue,
    ProductPerformance,
    FranchisePerformance,
    CustomerSpendingAnalysis,
    PaymentMethodAnalysis,
    GeographicSales,
    HourlySalesPattern,
    WelcomeMessage,
    KPIMetric,
    TimeSeriesPoint,
)

logger = getLogger(__name__)


class BIDashboardService:
    """Service class for fetching and processing BI analytics data"""

    @staticmethod
    def get_welcome_message() -> WelcomeMessage:
        """Get welcome message with emojis for dashboard greeting"""
        return WelcomeMessage(
            title="Welcome to your Bakery Sales Dashboard! 🥐📈📊",
            subtitle="Insights await you! ✨",
            emoji="👋",
            description="Discover powerful analytics for your bakery business - sales performance, customer insights, franchise metrics, and market trends all in one place",
        )

    @staticmethod
    def get_kpi_metrics(days: int = 30) -> List[KPIMetric]:
        """Fetch key performance indicators with trend analysis"""
        try:
            kpis_data = SalesKPIs.fetch(days=days)

            if not kpis_data:
                logger.warning("No KPI data available")
                return []

            kpi = kpis_data[0]

            # Calculate growth metrics (comparing with previous period)
            prev_kpis_data = list(SalesKPIs.fetch(days=days * 2))  # Get double the period for comparison
            growth_metrics = BIDashboardService._calculate_growth_metrics(kpi, prev_kpis_data, days)

            return [
                KPIMetric(
                    name="Total Revenue",
                    value=kpi.total_revenue,
                    unit="$",
                    change_percent=growth_metrics.get("revenue_growth"),
                    trend=BIDashboardService._get_trend(growth_metrics.get("revenue_growth")),
                    emoji="💰",
                ),
                KPIMetric(
                    name="Transactions",
                    value=kpi.total_transactions,
                    unit="",
                    change_percent=growth_metrics.get("transactions_growth"),
                    trend=BIDashboardService._get_trend(growth_metrics.get("transactions_growth")),
                    emoji="🛒",
                ),
                KPIMetric(
                    name="Avg Transaction",
                    value=kpi.avg_transaction_value,
                    unit="$",
                    change_percent=growth_metrics.get("avg_transaction_growth"),
                    trend=BIDashboardService._get_trend(growth_metrics.get("avg_transaction_growth")),
                    emoji="💳",
                ),
                KPIMetric(
                    name="Active Customers",
                    value=kpi.unique_customers,
                    unit="",
                    change_percent=growth_metrics.get("customers_growth"),
                    trend=BIDashboardService._get_trend(growth_metrics.get("customers_growth")),
                    emoji="👥",
                ),
                KPIMetric(name="Product Variety", value=kpi.unique_products, unit="", emoji="🍰"),
                KPIMetric(name="Active Franchises", value=kpi.unique_franchises, unit="", emoji="🏪"),
            ]
        except Exception as e:
            logger.error(f"Error fetching KPI metrics: {e}")
            return []

    @staticmethod
    def get_daily_revenue_trend(days: int = 30) -> List[TimeSeriesPoint]:
        """Get daily revenue trend data for charts"""
        try:
            revenue_data = DailySalesRevenue.fetch(days=days)

            return [
                TimeSeriesPoint(date=item.sale_date, value=item.total_revenue, label=f"${item.total_revenue:,.2f}")
                for item in revenue_data
            ]
        except Exception as e:
            logger.error(f"Error fetching daily revenue trend: {e}")
            return []

    @staticmethod
    def get_product_performance_data(days: int = 30, limit: int = 10) -> Dict[str, Any]:
        """Get top performing products with sales data"""
        try:
            products = ProductPerformance.fetch(days=days, limit=limit)

            return {
                "columns": [
                    {"name": "product", "label": "Product 🥐", "field": "product"},
                    {"name": "revenue", "label": "Revenue 💰", "field": "revenue", "sortable": True},
                    {"name": "quantity", "label": "Quantity 📊", "field": "quantity", "sortable": True},
                    {"name": "avg_price", "label": "Avg Price 💵", "field": "avg_price", "sortable": True},
                    {"name": "share", "label": "Market Share 📈", "field": "share", "sortable": True},
                ],
                "rows": [
                    {
                        "product": product.product,
                        "revenue": f"${product.total_revenue:,.2f}",
                        "quantity": f"{product.total_quantity:,}",
                        "avg_price": f"${product.avg_unit_price:.2f}",
                        "share": f"{product.revenue_percentage:.1f}%",
                    }
                    for product in products
                ],
            }
        except Exception as e:
            logger.error(f"Error fetching product performance: {e}")
            return {"columns": [], "rows": []}

    @staticmethod
    def get_franchise_performance_data(days: int = 30, limit: int = 15) -> Dict[str, Any]:
        """Get franchise performance metrics"""
        try:
            franchises = FranchisePerformance.fetch(days=days, limit=limit)

            return {
                "columns": [
                    {"name": "name", "label": "Franchise 🏪", "field": "name"},
                    {"name": "location", "label": "Location 🌍", "field": "location"},
                    {"name": "revenue", "label": "Revenue 💰", "field": "revenue", "sortable": True},
                    {"name": "transactions", "label": "Orders 🛒", "field": "transactions", "sortable": True},
                    {"name": "avg_order", "label": "Avg Order 💳", "field": "avg_order", "sortable": True},
                    {"name": "size", "label": "Size 📏", "field": "size"},
                ],
                "rows": [
                    {
                        "name": franchise.franchise_name,
                        "location": f"{franchise.city}, {franchise.country}",
                        "revenue": f"${franchise.total_revenue:,.2f}",
                        "transactions": f"{franchise.transaction_count:,}",
                        "avg_order": f"${franchise.avg_transaction_value:.2f}",
                        "size": franchise.size,
                    }
                    for franchise in franchises
                ],
            }
        except Exception as e:
            logger.error(f"Error fetching franchise performance: {e}")
            return {"columns": [], "rows": []}

    @staticmethod
    def get_customer_segments_data(days: int = 30) -> Dict[str, Any]:
        """Get customer segmentation analysis"""
        try:
            customers = CustomerSpendingAnalysis.fetch(days=days, limit=100)

            # Aggregate by segment
            segments = {}
            for customer in customers:
                segment = customer.customer_segment
                if segment not in segments:
                    segments[segment] = {"count": 0, "total_spent": 0.0, "avg_transactions": 0.0}
                segments[segment]["count"] += 1
                segments[segment]["total_spent"] += customer.total_spent
                segments[segment]["avg_transactions"] += customer.transaction_count

            # Calculate averages
            for segment_data in segments.values():
                if segment_data["count"] > 0:
                    segment_data["avg_spent"] = segment_data["total_spent"] / segment_data["count"]
                    segment_data["avg_transactions"] = segment_data["avg_transactions"] / segment_data["count"]

            return {
                "segments": segments,
                "chart_data": {
                    "labels": list(segments.keys()),
                    "values": [data["count"] for data in segments.values()],
                    "revenue": [data["total_spent"] for data in segments.values()],
                },
            }
        except Exception as e:
            logger.error(f"Error fetching customer segments: {e}")
            return {"segments": {}, "chart_data": {"labels": [], "values": [], "revenue": []}}

    @staticmethod
    def get_payment_methods_data(days: int = 30) -> Dict[str, Any]:
        """Get payment method preferences and performance"""
        try:
            payment_methods = PaymentMethodAnalysis.fetch(days=days)

            return {
                "chart_data": {
                    "labels": [method.payment_method for method in payment_methods],
                    "values": [method.percentage_of_transactions for method in payment_methods],
                    "revenue": [method.total_revenue for method in payment_methods],
                },
                "table_data": {
                    "columns": [
                        {"name": "method", "label": "Payment Method 💳", "field": "method"},
                        {"name": "transactions", "label": "Transactions 🛒", "field": "transactions", "sortable": True},
                        {"name": "percentage", "label": "Share 📊", "field": "percentage", "sortable": True},
                        {"name": "revenue", "label": "Revenue 💰", "field": "revenue", "sortable": True},
                        {"name": "avg_value", "label": "Avg Value 💵", "field": "avg_value", "sortable": True},
                    ],
                    "rows": [
                        {
                            "method": method.payment_method,
                            "transactions": f"{method.transaction_count:,}",
                            "percentage": f"{method.percentage_of_transactions:.1f}%",
                            "revenue": f"${method.total_revenue:,.2f}",
                            "avg_value": f"${method.avg_transaction_value:.2f}",
                        }
                        for method in payment_methods
                    ],
                },
            }
        except Exception as e:
            logger.error(f"Error fetching payment methods data: {e}")
            return {
                "chart_data": {"labels": [], "values": [], "revenue": []},
                "table_data": {"columns": [], "rows": []},
            }

    @staticmethod
    def get_geographic_performance(days: int = 30) -> Dict[str, Any]:
        """Get geographic sales performance by country"""
        try:
            geo_data = GeographicSales.fetch(days=days)

            return {
                "chart_data": {
                    "countries": [geo.country for geo in geo_data],
                    "revenue": [geo.total_revenue for geo in geo_data],
                    "customers": [geo.unique_customers for geo in geo_data],
                },
                "table_data": {
                    "columns": [
                        {"name": "country", "label": "Country 🌍", "field": "country"},
                        {"name": "revenue", "label": "Revenue 💰", "field": "revenue", "sortable": True},
                        {"name": "transactions", "label": "Orders 🛒", "field": "transactions", "sortable": True},
                        {"name": "customers", "label": "Customers 👥", "field": "customers", "sortable": True},
                        {"name": "franchises", "label": "Franchises 🏪", "field": "franchises", "sortable": True},
                        {"name": "avg_order", "label": "Avg Order 💳", "field": "avg_order", "sortable": True},
                    ],
                    "rows": [
                        {
                            "country": geo.country,
                            "revenue": f"${geo.total_revenue:,.2f}",
                            "transactions": f"{geo.transaction_count:,}",
                            "customers": f"{geo.unique_customers:,}",
                            "franchises": f"{geo.unique_franchises:,}",
                            "avg_order": f"${geo.avg_transaction_value:.2f}",
                        }
                        for geo in geo_data
                    ],
                },
            }
        except Exception as e:
            logger.error(f"Error fetching geographic performance: {e}")
            return {
                "chart_data": {"countries": [], "revenue": [], "customers": []},
                "table_data": {"columns": [], "rows": []},
            }

    @staticmethod
    def get_hourly_sales_pattern(days: int = 30) -> Dict[str, Any]:
        """Get hourly sales patterns for operational insights"""
        try:
            hourly_data = list(HourlySalesPattern.fetch(days=days))

            # Sort by hour to ensure proper order
            hourly_data.sort(key=lambda x: x.hour_of_day)

            return {
                "chart_data": {
                    "hours": [f"{hour.hour_of_day:02d}:00" for hour in hourly_data],
                    "transactions": [hour.transaction_count for hour in hourly_data],
                    "revenue": [hour.total_revenue for hour in hourly_data],
                },
                "peak_hour": max(hourly_data, key=lambda x: x.transaction_count).hour_of_day if hourly_data else 0,
                "peak_revenue_hour": max(hourly_data, key=lambda x: x.total_revenue).hour_of_day if hourly_data else 0,
            }
        except Exception as e:
            logger.error(f"Error fetching hourly sales pattern: {e}")
            return {
                "chart_data": {"hours": [], "transactions": [], "revenue": []},
                "peak_hour": 0,
                "peak_revenue_hour": 0,
            }

    @staticmethod
    def _calculate_growth_metrics(
        current_kpi: SalesKPIs, historical_data: List[SalesKPIs], days: int
    ) -> Dict[str, Optional[float]]:
        """Calculate growth percentages by comparing current period with previous period"""
        if len(historical_data) < 2:
            return {}

        try:
            # Find the previous period KPI (should be the difference between total and current period)
            total_kpi = historical_data[0]  # This includes both periods

            # Calculate previous period values
            prev_revenue = total_kpi.total_revenue - current_kpi.total_revenue
            prev_transactions = total_kpi.total_transactions - current_kpi.total_transactions
            prev_customers = total_kpi.unique_customers - current_kpi.unique_customers
            prev_avg_transaction = prev_revenue / prev_transactions if prev_transactions > 0 else 0

            return {
                "revenue_growth": BIDashboardService._calculate_percentage_change(
                    prev_revenue, current_kpi.total_revenue
                ),
                "transactions_growth": BIDashboardService._calculate_percentage_change(
                    prev_transactions, current_kpi.total_transactions
                ),
                "customers_growth": BIDashboardService._calculate_percentage_change(
                    prev_customers, current_kpi.unique_customers
                ),
                "avg_transaction_growth": BIDashboardService._calculate_percentage_change(
                    prev_avg_transaction, current_kpi.avg_transaction_value
                ),
            }
        except Exception as e:
            logger.warning(f"Error calculating growth metrics: {e}")
            return {}

    @staticmethod
    def _calculate_percentage_change(old_value: float, new_value: float) -> Optional[float]:
        """Calculate percentage change between two values"""
        if old_value == 0:
            return None
        return ((new_value - old_value) / old_value) * 100

    @staticmethod
    def _get_trend(change_percent: Optional[float]) -> str:
        """Determine trend direction based on percentage change"""
        if change_percent is None:
            return "neutral"
        if change_percent > 0:
            return "up"
        elif change_percent < 0:
            return "down"
        else:
            return "neutral"
