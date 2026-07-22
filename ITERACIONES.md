# Iteraciones

Este documento registra cómo evolucionó el agente: cada iteración parte de una **observación
empírica** sobre una corrida real, hace **un cambio concreto**, y mide el **resultado**.

El instrumento de medición es un **conjunto de referencia** de 22 casos etiquetados a mano
(`tests/test_classifier.py`): 9 observaciones reales del documento (incluidas las "trampas":
falsos positivos con score altísimo, coincidencias reales con score bajo, homónimos repetidos)
y 13 casos sintéticos de borde. Se corre sin llamar a la API, así que medir la lógica no cuesta
nada. Otros 6 casos (`tests/test_loader.py`) cubren la robustez de la lectura del documento.

---

## Iteración 1: MVP de punta a punta

**Objetivo:** que el pipeline completo corra sobre las 80 observaciones reales: leer el PDF,
extraer los campos con el modelo, clasificar con reglas, y escribir el CSV con logging de
tiempo y costo.

**Corrida:** 80/80 observaciones · **US$ 0.35** · **4 m 48 s** · modelo Haiku 4.5.

**Observaciones empíricas:**

1. **La extracción funciona incluso en las trampas.** El caso estrella (Obs. 5: cliente
   argentino, score 97 %, sujeto OFAC colombiano) se extrajo perfecto: el modelo separó
   cliente de sujeto aunque venían mezclados en la prosa, y normalizó las fechas de sus ocho
   formatos distintos a ISO. Confirma la decisión de arquitectura: el modelo es bueno leyendo,
   y las reglas pueden decidir sobre datos limpios.

2. **El agente de Strands es *stateful*, y eso costaba caro.** Al reusar un mismo objeto
   `Agent` para las 80 observaciones, cada llamada arrastraba el historial de las anteriores:
   la observación 5 llegó a **3.856 tokens de entrada** cuando debía rondar los 1.700. Además
   de inflar el costo, contaminaba un caso con los datos del anterior y arriesgaba desbordar el
   contexto hacia el caso 80.
   → **Cambio:** un **agente nuevo por observación**. El historial arranca vacío cada vez, el
   uso de tokens es exactamente el de esa observación, y una falla nunca afecta a la siguiente.
   Con el fix, la Obs. 5 bajó a **1.687 tokens** de entrada.

3. **La distribución dio 40 falsos positivos / 40 reales, demasiado pareja.** El enunciado y
   el dominio dicen que en screening la *gran mayoría* de las alertas son homónimos. Un 50/50
   olía a que el clasificador estaba siendo demasiado generoso al declarar "posible real".
   → Esto motivó la iteración 2.

**Estado del conjunto de referencia al final de la iteración 1:** 16/16.

---

## Iteración 2: afinar la lógica (no todas las señales pesan igual)

**Observación previa (de la iteración 1):** 16 de los 80 casos cayeron en la regla de
"evidencia mixta → posible real, media". Al mirarlos uno por uno, el patrón era claro: eran
casos donde **la fecha de nacimiento y el documento contradecían** (identificadores fuertes),
y lo único que coincidía era la **nacionalidad**. Ejemplos: Obs. 22, 36, 40, 48, con nombre
parcial, fecha distinta, documento distinto, y solo el país en común.

Tratar eso como "posible coincidencia real" es un error de criterio: compartir nacionalidad es
una señal **débil** (medio país la comparte), mientras que una fecha de nacimiento que
discrepa es una señal **fuerte** de que son personas distintas. Un homónimo colombiano no es
un caso para la cola del analista.

**Cambio:** se separó el peso de las señales.

- **Fuertes** (discriminantes): **documento** y **fecha de nacimiento**.
- **De apoyo** (débiles): **nacionalidad** y **lugar de nacimiento**.

El árbol de decisión se reescribió alrededor de esta distinción:

- Un identificador **fuerte** que contradice, sin ningún fuerte que confirme → **falso
  positivo** (homónimo), **aunque coincida la nacionalidad**. La nacionalidad ya no rescata un
  match que un identificador fuerte descarta.
- La prioridad **alta** se reserva para evidencia fuerte (documento idéntico, o varios
  identificadores fuertes, o un fuerte + programa severo). Una nacionalidad coincidente ya no
  empuja un caso a "alta".

**Resultado medido (misma extracción de la iteración 1, solo cambió el clasificador, costo
US$ 0):**

| | Falsos positivos | Posibles reales |
|---|---|---|
| Iteración 1 | 40 | 40 |
| Iteración 2 | **55** | **25** |

**15 observaciones** pasaron de "posible real" a "falso positivo", todas homónimos que antes
se colaban a la cola de revisión (Obs. 1, 2, 4, 12, 16, 22, 24, 28, 36, 38, 40, 47, 48, 52, 73).
La distribución quedó alineada con lo que dice el dominio: la mayoría son falsos positivos.

**Verificación de que no rompió las coincidencias reales:** los casos con documento idéntico
(Obs. 11, 23) o con todos los identificadores fuertes coincidiendo (Obs. 34, 60) siguieron
clasificándose como posible real, alta. El conjunto de referencia (que fue creciendo hasta 22
casos) siguió pasando al 100 %, incluido un caso agregado para el escalón "media": un
identificador fuerte coincide con programa no severo.

**Observación del escalón "media":** en el documento de ejemplo casi todos los sujetos OFAC
pertenecen a programas severos (narcotráfico, `SDNTK`). Por eso los matches confirmados
escalan a **alta** y el escalón **media** casi no se puebla en *este* documento particular.
No es un defecto: la regla del escalón medio existe y se ejercita en los tests; simplemente
este informe trae sujetos polarizados (o el documento coincide → real claro, o un identificador
fuerte discrepa → homónimo claro).

---

## Iteración 3: robustez y costo

**Objetivo:** garantizar que el agente corre en la máquina del evaluador contra **otro**
documento del mismo formato sin romperse, y dejar el costo bajo control.

**Observaciones previas:** el documento del regulador lo redacta un tercero; no se puede
asumir que esté bien formado. Hay que sobrevivir a campos faltantes, fechas ambiguas,
documentos con errores de tipeo, y cantidades de observaciones distintas a 80.

**Cambios:**

1. **La corrida nunca se cae por una observación.** Si la extracción de un caso falla, se
   registra como fila `ERROR_DE_EXTRACCION` (con el detalle técnico), se marca para revisión
   manual, y la corrida **continúa** con las demás. El analista igual recibe los otros 79 casos.

2. **Segmentación defensiva.** El segmentador no asume 80 observaciones ni una etiqueta fija:
   detecta las cinco etiquetas que rotan en el informe, respeta numeraciones con huecos y
   cantidades distintas, y ante un documento sin formato reconocible devuelve una lista vacía
   con un mensaje claro en vez de romper. Cubierto por `tests/test_loader.py` (6 casos).

3. **Documento con dígitos transpuestos.** Se detectó en el ejemplo un caso (Obs. 34) donde el
   número de documento del cliente y el del sujeto OFAC tienen **los mismos dígitos en distinto
   orden** (`01633018` vs `10633018`), con todo lo demás coincidiendo. Tratarlo como
   "documento distinto" sería descartar una probable coincidencia real por un error de tipeo
   del legajo. → Se agregó una señal específica: mismos dígitos en otro orden **no** cuenta ni
   como coincidencia ni como contradicción; se marca explícitamente en la justificación para
   que un humano lo confirme.

4. **Soporte de Word (`.docx`).** El enunciado describe el informe como "un documento de Word",
   aunque el ejemplo entregado es un PDF. Se agregó la lectura de `.docx` (párrafos y celdas de
   tabla) detrás de la misma interfaz, de modo que el resto del pipeline no cambia según el
   formato de entrada.

5. **Costo bajo control.** El clasificador y el justificador **no** usan el modelo: son Python
   determinista. El modelo se llama una sola vez por observación, para extraer. Con Haiku 4.5,
   una corrida completa de las 80 observaciones cuesta **~US$ 0.35** y tarda **~5 minutos**. El
   costo se mide desde el primer archivo (no se agregó al final) y se muestra por caso y total.

**Resultado:** el pipeline corre de punta a punta sobre el ejemplo y sobre documentos
mutilados de prueba sin lanzar excepciones, degradando con gracia en cada caso borde.

---

## Resumen de la evolución

| | Foco | Métrica |
|---|---|---|
| Iteración 1 | Pipeline completo funcionando | 80/80 corridas, US$ 0.35, hallazgo del agente *stateful* |
| Iteración 2 | Criterio de clasificación | 40/40 → 55/25 FP/reales; señales fuertes vs. de apoyo |
| Iteración 3 | Robustez y costo | Casos borde sin romper, soporte .docx, costo medido |
