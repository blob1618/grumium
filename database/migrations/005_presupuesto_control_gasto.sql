-- HU-PRE-01 / STK-47: control de gasto consumido por límite mensual.
-- La aplicación sigue accediendo por conexión PostgreSQL directa. No se otorgan
-- privilegios a anon/authenticated y RLS queda habilitado como defensa en profundidad.

BEGIN;

CREATE TABLE IF NOT EXISTS public.limite_categoria (
  id uuid NOT NULL DEFAULT uuid_generate_v4(),
  usuario_id uuid NOT NULL,
  categoria_id uuid NOT NULL,
  cantidad_max numeric(18, 2) NOT NULL,
  moneda varchar(3) NOT NULL DEFAULT 'ARS',
  inicio_periodo date NOT NULL,
  fin_periodo date NOT NULL,
  creado_en timestamp with time zone NOT NULL DEFAULT now(),
  actualizado_en timestamp with time zone NOT NULL DEFAULT now(),

  CONSTRAINT limite_categoria_pkey PRIMARY KEY (id),
  CONSTRAINT limite_categoria_usuario_id_fkey
    FOREIGN KEY (usuario_id) REFERENCES public.usuario(id) ON DELETE CASCADE,
  CONSTRAINT limite_categoria_categoria_id_fkey
    FOREIGN KEY (categoria_id) REFERENCES public.categorias(id) ON DELETE CASCADE
);

ALTER TABLE public.limite_categoria
  ADD COLUMN IF NOT EXISTS moneda varchar(3),
  ADD COLUMN IF NOT EXISTS actualizado_en timestamp with time zone;

UPDATE public.limite_categoria
SET moneda = upper(btrim(COALESCE(moneda, 'ARS')))
WHERE moneda IS NULL OR moneda <> upper(btrim(moneda));

UPDATE public.limite_categoria
SET actualizado_en = COALESCE(creado_en, now())
WHERE actualizado_en IS NULL;

ALTER TABLE public.limite_categoria
  ALTER COLUMN cantidad_max TYPE numeric(18, 2),
  ALTER COLUMN moneda SET DEFAULT 'ARS',
  ALTER COLUMN moneda SET NOT NULL,
  ALTER COLUMN actualizado_en SET DEFAULT now(),
  ALTER COLUMN actualizado_en SET NOT NULL;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM public.limite_categoria
    GROUP BY usuario_id, categoria_id, inicio_periodo, moneda
    HAVING count(*) > 1
  ) THEN
    RAISE EXCEPTION
      'Migración STK-47 abortada: existen límites duplicados por usuario/categoría/período/moneda';
  END IF;
END
$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'limite_categoria_usuario_id_fkey'
      AND conrelid = 'public.limite_categoria'::regclass
  ) THEN
    ALTER TABLE public.limite_categoria
      ADD CONSTRAINT limite_categoria_usuario_id_fkey
      FOREIGN KEY (usuario_id) REFERENCES public.usuario(id) ON DELETE CASCADE;
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'limite_categoria_categoria_id_fkey'
      AND conrelid = 'public.limite_categoria'::regclass
  ) THEN
    ALTER TABLE public.limite_categoria
      ADD CONSTRAINT limite_categoria_categoria_id_fkey
      FOREIGN KEY (categoria_id) REFERENCES public.categorias(id) ON DELETE CASCADE;
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'limite_categoria_cantidad_max_check'
      AND conrelid = 'public.limite_categoria'::regclass
  ) THEN
    ALTER TABLE public.limite_categoria
      ADD CONSTRAINT limite_categoria_cantidad_max_check CHECK (cantidad_max > 0);
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'limite_categoria_moneda_check'
      AND conrelid = 'public.limite_categoria'::regclass
  ) THEN
    ALTER TABLE public.limite_categoria
      ADD CONSTRAINT limite_categoria_moneda_check
      CHECK (char_length(moneda) = 3 AND moneda = upper(moneda));
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'limite_categoria_periodo_check'
      AND conrelid = 'public.limite_categoria'::regclass
  ) THEN
    ALTER TABLE public.limite_categoria
      ADD CONSTRAINT limite_categoria_periodo_check
      CHECK (inicio_periodo <= fin_periodo);
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'limite_categoria_usuario_categoria_periodo_moneda_key'
      AND conrelid = 'public.limite_categoria'::regclass
  ) THEN
    ALTER TABLE public.limite_categoria
      ADD CONSTRAINT limite_categoria_usuario_categoria_periodo_moneda_key
      UNIQUE (usuario_id, categoria_id, inicio_periodo, moneda);
  END IF;
END
$$;

CREATE INDEX IF NOT EXISTS limite_categoria_usuario_vigencia_idx
  ON public.limite_categoria (usuario_id, fin_periodo, inicio_periodo);

CREATE INDEX IF NOT EXISTS limite_categoria_categoria_id_idx
  ON public.limite_categoria (categoria_id);

CREATE INDEX IF NOT EXISTS movimientos_financieros_presupuesto_egresos_idx
  ON public.movimientos_financieros
  (usuario_id, categoria_id, moneda, fecha_movimiento)
  WHERE tipo = 'egreso' AND categoria_id IS NOT NULL;

ALTER TABLE public.limite_categoria ENABLE ROW LEVEL SECURITY;

COMMIT;
