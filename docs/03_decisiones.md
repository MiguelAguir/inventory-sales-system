# Decisiones de diseño

Registro de las decisiones que más afectan al sistema, con su motivo y su costo.
El objetivo es que otra persona pueda modificarlo sin tener que adivinar.

## D-01. PostgreSQL como único motor

**Decisión:** todo el modelo, las reglas y la analítica viven en PostgreSQL 16.

**Motivo:** un solo motor evita duplicar lógica entre aplicación y base, permite
usar transacciones, `CHECK`, funciones, triggers y vistas con SQL estándar.

**Costo:** el proyecto no demuestra portabilidad a MySQL. Es una limitación
consciente: el objetivo es profundidad en un motor, no cobertura superficial de
varios.

## D-02. `core` en 3NF, analítica en `reporting`

**Decisión:** las tablas operativas están normalizadas; las preguntas de negocio
se responden con vistas y dos *marts*.

**Motivo:** evita anomalías de actualización y duplicación de hechos. Las vistas
siempre reflejan el estado actual; los *marts* solo se usan donde conviene
precalcular.

**Costo:** algunas consultas analíticas recorren más tablas. A este volumen
(15k movimientos) el costo es despreciable.

## D-03. Libro mayor inmutable + saldo materializado

**Decisión:** `core.stock_movements` es la fuente de verdad y solo acepta
`INSERT`. `core.stock_levels` guarda el saldo y lo mantiene un trigger.

**Motivo:** el libro mayor permite auditar cualquier saldo y reconstruir el
inventario a una fecha. El saldo evita sumar todo el historial en cada consulta.

**Costo:** hay que mantener la coherencia entre ambos. Se resuelve con el trigger
y con un control de calidad que compara saldo contra suma del libro mayor.

## D-04. `UPDATE` condicional para evitar stock negativo

**Decisión:** al aplicar una salida se ejecuta un `UPDATE` con
`WHERE quantity + delta >= 0`. Si no actualiza ninguna fila, se lanza una
excepción.

**Motivo:** bajo concurrencia, dos transacciones que leen el saldo antes de
escribir pueden vender la misma unidad. El `UPDATE` atómico reevalúa la condición
después del bloqueo y serializa el acceso.

**Costo:** el mensaje de error debe explicar si no existe saldo o si es
insuficiente. Hay una prueba con dos hilos que compite por la última unidad.

## D-05. Funciones explícitas, no triggers que “adivinan” el negocio

**Decisión:** confirmar y cancelar se hacen con
`fn_confirm_sale` / `fn_cancel_sale` y equivalentes de compra. Un trigger de
cabecera exige una variable de sesión (`inventory.posting`) para permitir la
transición.

**Motivo:** si un trigger confirmara automáticamente al cambiar el estado, el
flujo quedaría oculto y sería difícil de depurar. Con funciones explícitas el
llamador sabe qué ocurre y el `UPDATE` directo falla con un mensaje claro.

**Costo:** la aplicación debe llamar a la función correcta; no basta con un
`UPDATE`. Es una restricción deliberada.

## D-06. Claves foráneas reales en el libro mayor

**Decisión:** `stock_movements` tiene `sale_id` y `purchase_id` con FK y un
`CHECK` de “exactamente una fuente” según el tipo de movimiento.

**Motivo:** una referencia polimórfica (`reference_id` + `reference_type`) no
puede tener FK y permite datos huérfanos. Con dos columnas opcionales la
integridad la garantiza el motor.

**Costo:** agregar un nuevo documento que mueva stock requiere una columna o un
cambio de modelo, en vez de reutilizar un campo genérico.

## D-07. Precio y costo congelados en la línea

**Decisión:** `sale_items.unit_price` y `sale_items.unit_cost` se copian al
registrar la venta. `purchase_items.unit_cost` se copia al registrar la compra.

**Motivo:** si el catálogo cambia de precio, el historial no debe cambiar. El
margen de una venta pasada tiene que ser reproducible.

**Costo:** el costo congelado no se actualiza solo; la valorización actual usa
el costo estándar del producto (ver limitaciones).

## D-08. Columnas generadas para importes de línea

**Decisión:** `line_subtotal`, `line_cost` y el subtotal de compra son columnas
`GENERATED ... STORED`.

**Motivo:** evita que la aplicación calcule y escriba importes que pueden quedar
inconsistentes con cantidad, precio y descuento.

**Costo:** cambiar la fórmula exige recrear la columna. A cambio, el dato siempre
es derivable y consistente.

## D-09. IGV configurable en `core.settings`

**Decisión:** la tasa se lee con `core.fn_igv_rate()` desde
`core.settings ('igv_rate', 0.18)`.

**Motivo:** evita constantes repartidas por el código y permite cambiar la tasa
sin recompilar. El control de calidad verifica que sea un valor entre 0 y 1.

**Costo:** cambiar la tasa afecta a documentos nuevos; los totales ya guardados
no se recalculan (son históricos).

## D-10. Datos sintéticos con semilla fija

**Decisión:** el generador usa `random.Random(42)`, 24 meses móviles, 60
productos, 200 clientes, 20 proveedores y 2 almacenes.

**Motivo:** un portafolio necesita datos reproducibles y sin riesgo de privacidad.
La semilla fija permite comparar resultados entre ejecuciones.

**Costo:** los datos no tienen la complejidad de un negocio real; las
conclusiones son del dataset, no del mercado.

## D-11. CLI + Metabase, sin CRUD web

**Decisión:** la operación se hace con `python -m src.pipeline`; la exploración,
con Metabase.

**Motivo:** el objetivo es demostrar SQL, modelado y análisis, no desarrollo
frontend. Una CLI es rápida de auditar y no distrae del núcleo.

**Costo:** no hay una experiencia de usuario final. Para un caso real habría que
agregar una capa de aplicación y autenticación.

## D-12. Todo idempotente

**Decisión:** el DDL usa `IF NOT EXISTS` / `CREATE OR REPLACE`; el setup de
Metabase busca por nombre antes de crear; el sembrado exige `--reset` si ya hay
datos.

**Motivo:** se puede volver a ejecutar sin romper el entorno, algo útil en demos y
en CI. Las pruebas aplican el esquema dos veces para verificarlo.

**Costo:** los cambios de definición de una vista materializada requieren `DROP`
manual; no se detectan solos.

## D-13. Orden estable de bloqueos

**Decisión:** al confirmar o cancelar, las líneas se procesan `ORDER BY
product_id`.

**Motivo:** dos documentos que tocan los mismos productos toman los bloqueos en
el mismo orden y reducen el riesgo de *deadlock*.

**Costo:** no elimina todos los deadlocks posibles, pero cubre el patrón más
común del sistema.

## D-14. No se borran ventas ni compras

**Decisión:** un trigger `BEFORE DELETE` lo impide; el borrador se elimina o se
confirma, y el documento confirmado se cancela.

**Motivo:** conserva la trazabilidad y evita que un `DELETE` accidental se lleve
movimientos de stock.

**Costo:** la limpieza de datos de prueba se hace con `TRUNCATE`, no con
`DELETE` fila a fila.
