# Limitaciones y siguientes pasos

Este documento existe para que el proyecto no se lea como más de lo que es. Un
portafolio gana credibilidad cuando dice qué no hace y por qué.

## Limitaciones del alcance

### Los datos son sintéticos

El generador produce nombres, RUC, DNI y direcciones inventados. Los documentos
solo cumplen el formato peruano; **no se valida el dígito verificador** y no
corresponden a personas o empresas reales.

Consecuencias:

- Las cifras sirven para demostrar el diseño, no para concluir nada del mercado.
- Los patrones (Pareto, estacionalidad, rotación) fueron inducidos por el
  generador; son plausibles, no hallazgos empíricos.
- El periodo son 24 meses móviles que terminan ayer. Regenerar el dataset otro
  día cambia los totales, aunque la semilla sea la misma.

### No hay devoluciones parciales ni notas de crédito

Una venta se cancela completa. No existe devolver una línea, cambiar un producto
o emitir una nota de crédito. Para un negocio real esto es necesario y hoy
quedaría fuera del modelo.

### El costo de inventario no es FIFO ni promedio ponderado

La valorización actual (`v_stock_actual.stock_value`) usa el **costo estándar
del catálogo** (`products.unit_cost`). No usa el costo congelado de la línea ni
calcula promedio ponderado.

- La venta sí congela `unit_cost` en `sale_items`, así que el margen histórico es
  correcto.
- El valor del inventario de hoy es una aproximación, no una valorización
  contable.
- `fn_inventory_value_at()` usa el último costo conocido en el libro mayor, que
  es más fiel para series históricas, pero tampoco es un método contable formal.

### Un solo rol de base de datos

Todo corre con el usuario `inventory`, dueño del esquema. No hay separación entre
quien vende, quien compra y quien solo consulta; tampoco hay auditoría de
usuarios. En producción haría falta, como mínimo:

- un rol de aplicación con permisos de escritura acotados;
- un rol de solo lectura para BI;
- registro de quién ejecutó cada operación.

### No es un sistema listo para producción

- No hay API ni interfaz web; la operación es por CLI.
- No hay autenticación, autorización ni bitácora de acceso.
- No hay respaldos automáticos, réplica ni alta disponibilidad.
- Metabase corre con H2 embebido y un solo contenedor; es una demo local.
- Las credenciales están en `.env` y son de desarrollo.
- No hay facturación electrónica, SUNAT, múltiples monedas ni impuestos por
  producto.

### El alcance de rendimiento es pequeño

El dataset tiene ~15 mil movimientos y ~6.5 mil ventas. El benchmark compara
planes con y sin índices, pero a este volumen el planeador puede elegir un
*sequential scan* aunque exista un índice. Las conclusiones son relativas a este
tamaño:

- Los índices selectivos sí muestran una mejora clara (8.50× en el libro mayor).
- La agregación global no mejora (1.13×) porque hay que leer casi toda la tabla.
- No se probó particionamiento, réplica de lectura ni caché.

### El motor es PostgreSQL y nada más

El proyecto no demuestra portabilidad a MySQL, SQL Server u Oracle. Es una
decisión deliberada: profundidad en un motor en vez de cobertura superficial.
Las funciones, triggers y tipos `GENERATED` son específicos de PostgreSQL.

### La CLI no reemplaza un ERP

No hay interfaz de usuario, validación de formularios, manejo de sesiones ni
flujo de aprobación. Los comandos son para demostrar el modelo, no para operar
un negocio real.

## Limitaciones de las consultas

- El análisis ABC usa ingresos sin IGV y un corte 80/95 fijo; no es configurable
  desde la base.
- La estacionalidad promedia meses calendario con solo dos observaciones por mes
  (24 meses). Es descriptiva, no inferencial.
- La rotación usa COGS e inventario promedio; con un solo año de historia no
  distingue tendencia de estacionalidad.
- El “stock muerto” depende de una ventana de 90 días elegida a mano.
- El ticket promedio del tablero incluye IGV; las consultas analíticas no. Está
  documentado, pero es una fuente de confusión si no se lee.

## Lo que sí demuestra el proyecto

- Modelado relacional en 3NF con restricciones reales.
- Uso de libro mayor inmutable y saldo materializado consistente.
- Reglas de negocio en la base, no solo en la aplicación.
- Concurrencia resuelta con un `UPDATE` condicional y probada con dos hilos.
- SQL analítico con ventanas, CTE, vistas y funciones.
- Medición de rendimiento con `EXPLAIN (ANALYZE, BUFFERS)` y conclusiones
  honestas.
- Automatización de punta a punta: esquema, datos, calidad, consultas, BI.
- Documentación de decisiones y límites.

## Siguientes pasos sugeridos

En orden de valor para un caso real:

1. **Devoluciones parciales y notas de crédito**, con el mismo patrón de libro
   mayor y funciones idempotentes.
2. **Valorización contable** (promedio ponderado o FIFO) y cierre de inventario
   por periodo.
3. **Roles y permisos**: escritura para operación, lectura para BI, auditoría de
   accesos.
4. **API o interfaz mínima** para registrar ventas sin usar la CLI.
5. **Particionamiento por fecha** en `stock_movements` y `sales` si el volumen
   crece.
6. **Orquestación** (por ejemplo, un cron o un job) para refrescar *marts* y
   ejecutar los controles cada noche.
7. **Metabase con PostgreSQL como base de aplicación** y respaldos.
8. **Pruebas de carga** con un volumen realista para validar los índices.

Ninguno de estos pasos es necesario para entender el proyecto; son la lista de
lo que haría falta para llevarlo a producción.
