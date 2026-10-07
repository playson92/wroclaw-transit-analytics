INSERT INTO gold.active_services (analysis_id, dataset_id, service_date, service_id)
SELECT ctx.analysis_id, s.dataset_id, s.service_date, s.service_id
FROM wta_services s CROSS JOIN wta_context ctx
