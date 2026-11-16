# Calidad y pruebas

Hay dos capas de verificación que se complementan:

1. **Controles de calidad en SQL** sobre los datos reales de desarrollo.
2. **Pruebas automatizadas con pytest** sobre una base limpia e independiente.

La primera responde “¿los datos que tengo ahora son coherentes?”. La segunda
responde “¿el sistema sigue cumpliendo las reglas cuando lo uso?”.

## Controles de calidad

```bash
python -m src.pipeline quality
```

El CLI ejecuta `sql/20_checks/01_quality_checks.sql`, imprime una tabla y guarda
cada fila en `audit.quality_results` (`check_name`, `passed`, `detail`,
`checked_at`). Así queda historial de cuándo se validó el sistema.

### Los 13 controles

| Control | Qué verifica |
|---|---|
| Ventas: totales cuadran con líneas | `subtotal`, `tax` y `total` de la cabecera igualan la suma de líneas y la tasa de IGV. |
| Compras: totales cuadran con líneas | La misma conciliación para compras confirmadas. |
| Inventario: saldo = suma del libro mayor | `stock_levels.quantity` coincide con `sum(quantity_delta)` por producto/almacén. |
| Inventario: no hay saldos negativos | Ninguna fila de `stock_levels` tiene cantidad menor que cero. |
| Ventas confirmadas tienen movimientos SALE | Toda venta confirmada o cancelada tiene su posteo de salida. |
| Ventas canceladas tienen reversa SALE_CANCEL | Toda venta cancelada tiene su movimiento de reversa. |
| Compras confirmadas tienen movimientos PURCHASE | Toda compra confirmada o cancelada tiene su entrada. |
| Ventas: una línea por producto | No hay dos líneas del mismo producto en una venta. |
| Ventas confirmadas con total positivo | Ninguna venta confirmada tiene total ≤ 0. |
| Fechas de venta no futuras | Ninguna venta confirmada supera la fecha actual en más de un día. |
| ABC: las tres clases tienen productos | La clasificación devuelve A, B y C con al menos una fila cada una. |
| Configuración: tasa IGV válida | `igv_rate` existe y está entre 0 y 1 exclusivo. |
| Libro mayor: trigger de inmutabilidad activo | El trigger `trg_stock_movements_immutable` existe. |

### Resultado actual

```text
13/13 controles aprobados
A=7, B=15, C=36
0 ventas con diferencia, 0 compras con diferencia
0 combinaciones producto/almacén descuadradas
0 saldos negativos
IGV = 0.1800
```

Los controles están escritos como una sola consulta con `UNION ALL`, así que se
pueden ejecutar también desde cualquier cliente SQL sin depender de Python.

## Pruebas automatizadas

```bash
python -m pytest -q
```

### Aislamiento

`tests/conftest.py` crea la base `inventory_test` al inicio de la sesión, aplica
todo el esquema y la elimina al final. Entre pruebas hace `TRUNCATE` de las
tablas operativas y vuelve a sembrar un escenario mínimo. **No toca la base
`inventory` de desarrollo.**

Si PostgreSQL no está disponible, la suite se salta con un mensaje claro en
lugar de fallar de forma confusa.

### Cobertura por tema

| Tema | Qué se prueba |
|---|---|
| Totales e IGV | Subtotal, impuesto y total de una venta; coincidencia con las líneas. |
| Inventario y libro mayor | El saldo siempre es igual a la suma de movimientos. |
| Venta sin stock | Falla de forma atómica; no deja cabecera, líneas ni movimientos parciales. |
| Cancelación | Revierte el stock y es idempotente al ejecutarla dos veces. |
| Inmutabilidad | `UPDATE`/`DELETE` sobre movimientos falla; editar una cabecera confirmada falla. |
| Confirmación directa | Un `UPDATE` a `CONFIRMED` sin pasar por la función es rechazado. |
| Idempotencia | Confirmar dos veces no duplica el posteo. |
| Compras | Confirmar aumenta stock; cancelar lo reduce; cancelar no puede dejar saldo negativo. |
| Transferencias | Mueven stock entre almacenes sin cambiar el total del sistema. |
| Stock mínimo | `fn_set_min_stock` y la vista de bajo mínimo reflejan el cambio. |
| Concurrencia | Dos conexiones compiten por la última unidad: solo una gana. |
| Esquema | Tablas, vistas, enums, columnas generadas, triggers e índices de idempotencia. |
| Vistas | Totales y clasificación ABC consistentes; sin stock negativo tras vender. |
| Proyecto | Archivos obligatorios y aviso de datos sintéticos en el README. |

Resultado actual: **24 pruebas aprobadas**.

### La prueba de concurrencia

Es la más valiosa del conjunto. Dos hilos abren conexiones separadas e intentan
vender la misma última unidad del mismo producto y almacén. El diseño usa un
`UPDATE` condicional:

```sql
UPDATE core.stock_levels
   SET quantity = quantity + NEW.quantity_delta
 WHERE product_id = NEW.product_id
   AND warehouse_id = NEW.warehouse_id
   AND quantity + NEW.quantity_delta >= 0;
```

Solo una transacción actualiza la fila; la otra no encuentra fila y la venta
falla. La prueba verifica que el saldo final es 0 y que existe exactamente un
movimiento de venta.

## Integración continua

`.github/workflows/ci.yml` levanta PostgreSQL 16 como servicio, instala las
dependencias, aplica el esquema **dos veces** (para comprobar idempotencia) y
ejecuta toda la suite. No necesita Docker dentro del runner.

## Qué no cubre

- No hay pruebas de carga ni de estrés más allá del caso de concurrencia.
- No se validan RUC/DNI con dígito verificador; solo formato.
- Los controles asumen que el dataset sintético está completo; no detectan
  fraude ni errores de captura humana.
- La idempotencia se prueba en el flujo normal, no ante caídas del proceso a
  mitad de una transacción (eso lo garantiza PostgreSQL, no una prueba).

Ver [Limitaciones](08_limitaciones.md) para el contexto completo.
