from app.site_anomaly_aggregation import aggregate_site_anomaly_data


def aggregate_management_review_order_data(request):
    return aggregate_site_anomaly_data(request)
