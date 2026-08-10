-- STK-89: enlaces mágicos de acceso al dashboard para usuarios ya vinculados.
-- Independiente de public.onboarding_invitacion (STK-143), que sólo cubre altas nuevas.

BEGIN;

CREATE TABLE public.dashboard_login_link (
  id uuid NOT NULL DEFAULT uuid_generate_v4(),
  usuario_id uuid NOT NULL,
  token_hash text NOT NULL,
  estado text NOT NULL DEFAULT 'pendiente',
  expira_en timestamp with time zone NOT NULL,
  reenvios integer NOT NULL DEFAULT 0,
  ultimo_envio_en timestamp with time zone NULL,
  consumido_en timestamp with time zone NULL,
  creado_en timestamp with time zone NOT NULL DEFAULT now(),
  actualizado_en timestamp with time zone NOT NULL DEFAULT now(),

  CONSTRAINT dashboard_login_link_pkey PRIMARY KEY (id),
  CONSTRAINT dashboard_login_link_token_hash_key UNIQUE (token_hash),
  CONSTRAINT dashboard_login_link_token_hash_no_vacio_check
    CHECK (btrim(token_hash) <> ''),
  CONSTRAINT dashboard_login_link_estado_check
    CHECK (estado IN ('pendiente', 'consumido', 'vencido')),
  CONSTRAINT dashboard_login_link_reenvios_check CHECK (reenvios >= 0),
  CONSTRAINT dashboard_login_link_expiracion_check CHECK (expira_en > creado_en),
  CONSTRAINT dashboard_login_link_estado_campos_check
    CHECK (
      (estado = 'pendiente' AND consumido_en IS NULL)
      OR (estado = 'consumido' AND consumido_en IS NOT NULL)
      OR (estado = 'vencido' AND consumido_en IS NULL)
    ),
  CONSTRAINT dashboard_login_link_usuario_id_fkey
    FOREIGN KEY (usuario_id)
    REFERENCES public.usuario(id)
    ON DELETE CASCADE
);

CREATE INDEX dashboard_login_link_usuario_id_idx
  ON public.dashboard_login_link (usuario_id);

CREATE INDEX dashboard_login_link_estado_expira_idx
  ON public.dashboard_login_link (estado, expira_en);

CREATE UNIQUE INDEX dashboard_login_link_usuario_pendiente_uidx
  ON public.dashboard_login_link (usuario_id)
  WHERE estado = 'pendiente';

ALTER TABLE public.dashboard_login_link ENABLE ROW LEVEL SECURITY;

COMMIT;
