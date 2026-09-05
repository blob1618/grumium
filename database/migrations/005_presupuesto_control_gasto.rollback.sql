-- Rollback conservador de HU-PRE-01 / STK-47.
-- No elimina public.limite_categoria porque puede ser una tabla preexistente.

BEGIN;

DROP INDEX IF EXISTS public.movimientos_financieros_presupuesto_egresos_idx;
DROP INDEX IF EXISTS public.limite_categoria_usuario_vigencia_idx;
DROP INDEX IF EXISTS public.limite_categoria_categoria_id_idx;

ALTER TABLE public.limite_categoria
  DROP CONSTRAINT IF EXISTS limite_categoria_usuario_categoria_periodo_moneda_key,
  DROP CONSTRAINT IF EXISTS limite_categoria_periodo_check,
  DROP CONSTRAINT IF EXISTS limite_categoria_moneda_check;

ALTER TABLE public.limite_categoria
  DROP COLUMN IF EXISTS actualizado_en,
  DROP COLUMN IF EXISTS moneda;

COMMIT;
