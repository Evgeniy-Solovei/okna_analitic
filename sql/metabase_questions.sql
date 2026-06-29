-- Эти запросы можно использовать вручную в Metabase SQL editor,
-- если автоматический bootstrap через API не сработает.

-- KPI: общий срез за демо-период
SELECT
  SUM(leads) AS leads,
  SUM(target_leads) AS target_leads,
  SUM(zz) AS zz,
  ROUND(1.0 * SUM(zz) / NULLIF(SUM(target_leads), 0), 4) AS conversion,
  SUM(contracts) AS contracts,
  SUM(contract_amount) AS contract_amount,
  ROUND(1.0 * SUM(contract_amount) / NULLIF(SUM(contracts), 0), 0) AS avg_check
FROM v_manager_daily_metrics;

-- Динамика по дням
SELECT
  metric_date,
  SUM(target_leads) AS target_leads,
  SUM(zz) AS zz,
  SUM(contracts) AS contracts,
  SUM(contract_amount) AS contract_amount
FROM v_manager_daily_metrics
GROUP BY metric_date
ORDER BY metric_date;

-- Конверсия по менеджерам
SELECT
  manager,
  SUM(target_leads) AS target_leads,
  SUM(zz) AS zz,
  ROUND(1.0 * SUM(zz) / NULLIF(SUM(target_leads), 0), 4) AS conversion
FROM v_manager_daily_metrics
GROUP BY manager
ORDER BY conversion DESC;

-- Сумма договоров по менеджерам
SELECT
  manager,
  SUM(contracts) AS contracts,
  SUM(contract_amount) AS contract_amount,
  ROUND(1.0 * SUM(contract_amount) / NULLIF(SUM(contracts), 0), 0) AS avg_check
FROM v_manager_daily_metrics
GROUP BY manager
ORDER BY contract_amount DESC;

-- Направления
SELECT
  direction,
  SUM(leads) AS leads,
  SUM(target_leads) AS target_leads,
  SUM(zz) AS zz,
  ROUND(1.0 * SUM(zz) / NULLIF(SUM(target_leads), 0), 4) AS conversion,
  SUM(contract_amount) AS contract_amount
FROM v_manager_daily_metrics
GROUP BY direction
ORDER BY contract_amount DESC;

