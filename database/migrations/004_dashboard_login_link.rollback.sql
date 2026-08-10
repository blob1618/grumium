-- Rollback de STK-89. Se niega a ejecutar si hay enlaces ya consumidos,
-- para no perder el rastro de accesos reales al dashboard.

BEGIN;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM public.dashboard_login_link WHERE estado = 'consumido'
  ) THEN
    RAISE EXCEPTION
      'Rollback STK-89 abortado: existen enlaces de acceso ya consumidos';
  END IF;
END
$$;

DROP TABLE public.dashboard_login_link;

COMMIT;
