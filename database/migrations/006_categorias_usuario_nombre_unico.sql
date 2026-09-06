-- STK-46/STK-47: impedir categorías activas duplicadas por usuario.
--
-- Ejecutar primero la consulta de auditoría. Si devuelve filas, reconciliar los
-- duplicados antes de crear el índice para no elegir una categoría de forma
-- destructiva o ambigua.

SELECT
    usuario_id,
    lower(btrim(nombre)) AS nombre_normalizado,
    count(*) AS cantidad
FROM public.categorias
WHERE esta_eliminado = false
GROUP BY usuario_id, lower(btrim(nombre))
HAVING count(*) > 1;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM public.categorias
        WHERE esta_eliminado = false
        GROUP BY usuario_id, lower(btrim(nombre))
        HAVING count(*) > 1
    ) THEN
        RAISE EXCEPTION
            'No se puede crear categorias_usuario_nombre_activo_uidx: existen categorías activas duplicadas';
    END IF;
END
$$;

CREATE UNIQUE INDEX IF NOT EXISTS categorias_usuario_nombre_activo_uidx
    ON public.categorias (usuario_id, lower(btrim(nombre)))
    WHERE esta_eliminado = false;
