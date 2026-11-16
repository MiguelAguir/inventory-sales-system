# Requerimientos

## Contexto

Una distribuidora pequeña opera con **dos almacenes** (Central y Sur), compra a
proveedores y vende a empresas y personas. Hoy lleva el inventario en hojas de
cálculo: no hay una fuente única de verdad, el stock se descuadra y no se puede
saber con rapidez qué productos reponer ni cuánto capital está inmovilizado.

El objetivo del proyecto es demostrar, con un caso acotado, cómo se diseña y
opera un sistema transaccional de inventario y ventas en PostgreSQL, con
analítica encima. No busca competir con un ERP comercial.

## Objetivo

Construir un sistema reproducible que:

1. Registre compras, ventas, transferencias y ajustes con reglas de negocio
   verificables.
2. Mantenga el stock consistente incluso bajo concurrencia.
3. Permita responder preguntas de negocio con SQL y con un tablero de BI.
4. Sea fácil de entender, ejecutar y modificar por otra persona.

## Alcance

### Incluido

- Dos almacenes.
- Catálogo de productos con categorías jerárquicas y proveedores por producto.
- Compras a proveedores con IGV.
- Ventas a clientes con IGV y descuento por línea.
- Cancelación de ventas y compras con reversa de stock.
- Transferencias entre almacenes.
- Ajustes de inventario y stock mínimo por producto/almacén.
- Libro mayor de movimientos inmutable y saldo materializado.
- Vistas de ventas, margen, rotación, ABC, alertas y stock muerto.
- CLI para operar y validar.
- Tablero de Metabase.
- Datos sintéticos reproducibles.
- Controles de calidad y pruebas automatizadas.

### Fuera de alcance

- Interfaz web CRUD o API HTTP.
- Facturación electrónica, SUNAT, notas de crédito y devoluciones parciales.
- Múltiples monedas, impuestos por producto o retenciones.
- Costeo FIFO, promedio ponderado o valorización por lote.
- Gestión de usuarios, roles y permisos por área.
- Despliegue en producción, alta disponibilidad o respaldos automáticos.
- Integración con un ERP o con lectores de código de barras.

## Actores

| Actor | Necesidad |
|---|---|
| Analista de datos | Consultar ventas, margen, rotación y alertas con SQL. |
| Jefe de almacén | Saber qué reponer, cuánto hay y qué está inmovilizado. |
| Administrador | Registrar compras, ventas, transferencias y ajustes. |
| Evaluador del portafolio | Entender el diseño y reproducir el proyecto en minutos. |

## Requerimientos funcionales

| ID | Requerimiento |
|---|---|
| RF-01 | Registrar una venta con una o más líneas, precio, descuento y almacén. |
| RF-02 | Calcular subtotal, IGV y total con una tasa configurable. |
| RF-03 | Rechazar una venta si algún producto no tiene stock suficiente. |
| RF-04 | Confirmar y cancelar ventas de forma idempotente, con reversa de stock. |
| RF-05 | Registrar compras y aumentar stock al confirmarlas. |
| RF-06 | Impedir cancelar una compra si dejaría stock negativo. |
| RF-07 | Transferir stock entre almacenes sin alterar el total del sistema. |
| RF-08 | Ajustar stock con un motivo y registrar el movimiento. |
| RF-09 | Configurar stock mínimo por producto/almacén y listar faltantes. |
| RF-10 | Clasificar productos por ingreso (ABC) y calcular rotación. |
| RF-11 | Refrescar vistas materializadas para BI. |
| RF-12 | Ejecutar controles de calidad y conservar el resultado. |

## Requerimientos no funcionales

| ID | Requerimiento |
|---|---|
| RNF-01 | PostgreSQL 16 como único motor. |
| RNF-02 | Modelo operativo en 3NF; analítica en vistas, no en tablas duplicadas. |
| RNF-03 | Dinero en `numeric(12,2)`; fechas en `timestamptz`. |
| RNF-04 | El stock nunca puede quedar negativo. |
| RNF-05 | Los movimientos de inventario son inmutables. |
| RNF-06 | Los documentos confirmados no se editan; se cancelan con reversa. |
| RNF-07 | El DDL y el setup de Metabase son idempotentes. |
| RNF-08 | Los datos sintéticos se regeneran con la misma semilla. |
| RNF-09 | El proyecto corre localmente con Docker Compose y Python 3.12. |
| RNF-10 | La suite de pruebas no depende de la base de desarrollo. |

## Supuestos

- Un producto tiene un precio y costo de catálogo; la venta congela ambos.
- El IGV es único para todo el negocio (18%).
- Cada línea de venta referencia un producto distinto (restricción `UNIQUE`).
- No hay devoluciones parciales: una venta se cancela completa.
- Los RUC y DNI son sintéticos y solo validan formato, no dígito verificador.
- El periodo de demostración son 24 meses móviles que terminan ayer.

## Criterios de aceptación

1. `docker compose up -d` deja PostgreSQL y Metabase activos.
2. `python -m src.pipeline schema` aplica el DDL dos veces sin errores.
3. `python -m src.pipeline seed --reset` genera el mismo volumen con semilla 42.
4. `python -m src.pipeline quality` devuelve 13/13 controles aprobados.
5. `python -m src.pipeline queries` ejecuta las 11 consultas sin errores.
6. `python -m pytest -q` termina con 24 pruebas aprobadas.
7. `python -m src.pipeline metabase` deja un tablero con seis tarjetas.
8. La venta sin stock falla y no deja efectos parciales.
