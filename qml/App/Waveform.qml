import QtQuick
import App

// Реальный график пропускной способности. Принципы плавности:
//  1) EMA-сглаживание применяется ОДИН раз на каждую новую точку от Backend (1Hz), не каждый кадр.
//  2) Плавный скролл влево через дробную phase (60fps): между sample-точками линия движется,
//     не дёргается. phase сбрасывается при поступлении новой точки.
//  3) Пиковая нормализация тоже EMA — амплитуда меняется плавно, без резких прыжков масштаба.
Item {
    id: root
    implicitHeight: 96

    property bool active: backend.status === "connected"

    readonly property int _count: 84
    readonly property int _stepMs: 1000        // период одного сэмпла = тик Backend (1Hz)

    // Локальные сглаженные буферы (download / upload)
    property var _vDown: []
    property var _vUp:   []
    property real _phase: 0                    // 0..1 внутри одного шага — для дробного скролла
    property real _peakSmoothed: 0.05          // EMA пика, чтобы нормализация дышала плавно

    Component.onCompleted: {
        var a = [], b = []
        for (var i = 0; i < _count; i++) { a.push(0); b.push(0) }
        _vDown = a
        _vUp = b
    }

    // Принимаем НОВЫЙ sample от Backend: сдвигаем буфер влево + EMA-сглаживание + обновляем пик.
    function _ingest() {
        var srcD = backend.trafficHistDown
        var srcU = backend.trafficHistUp
        if (!srcD || srcD.length === 0) return
        var newD = srcD[srcD.length - 1]
        var newU = srcU[srcU.length - 1]
        if (newD === undefined) newD = 0
        if (newU === undefined) newU = 0

        var a = _vDown, b = _vUp
        var prevD = a.length > 0 ? a[a.length - 1] : 0
        var prevU = b.length > 0 ? b[b.length - 1] : 0
        // EMA 0.78/0.22 — спокойный отклик: резкие всплески сетевого I/O визуально не пилят
        var smD = prevD * 0.78 + newD * 0.22
        var smU = prevU * 0.78 + newU * 0.22
        a.shift(); a.push(smD)
        b.shift(); b.push(smU)
        _vDown = a
        _vUp = b
        _phase = 0      // новая точка стала "head" — двигаемся к ней

        // peak normalization: VU-meter паттерн — мгновенный rise (чтобы график сразу влез после
        // подключения), медленный decay (чтобы масштаб не дёргался когда пик упал).
        var curMax = 0
        for (var i = 0; i < a.length; i++) {
            if (a[i] > curMax) curMax = a[i]
            if (b[i] > curMax) curMax = b[i]
        }
        var target = Math.max(curMax, 0.05)
        if (target > _peakSmoothed) _peakSmoothed = target                      // instant rise
        else _peakSmoothed = _peakSmoothed * 0.95 + target * 0.05               // slow decay
    }

    Connections {
        target: backend
        function onStatsChanged() { root._ingest() }
    }

    Timer {
        interval: 16
        running: true
        repeat: true
        onTriggered: {
            // Плавный сдвиг влево между новыми sample'ами; clamped 0..1 пока ждём следующий ingest
            if (root._phase < 1) {
                root._phase = Math.min(1, root._phase + interval / root._stepMs)
            }
            canvas.requestPaint()
        }
    }

    Canvas {
        id: canvas
        anchors.fill: parent
        antialiasing: true
        renderStrategy: Canvas.Cooperative
        onPaint: {
            var ctx = getContext("2d")
            ctx.reset()
            var aD = root._vDown, aU = root._vUp
            var n = aD.length
            if (n < 3) return
            var w = width, h = height
            var baseline = h * 0.88
            var amp = h * 0.78
            var peak = root._peakSmoothed
            var step = w / (n - 2)
            var off = root._phase * step      // дробный сдвиг влево внутри одного шага

            function px(i) { return i * step - off }
            function pyD(i) { return baseline - (aD[i] / peak) * amp }
            function pyU(i) { return baseline - (aU[i] / peak) * amp }

            function drawLayer(points, color, fillAlpha) {
                ctx.beginPath()
                ctx.moveTo(px(0), points(0))
                for (var i = 1; i < n; i++) {
                    var mx = (px(i - 1) + px(i)) / 2
                    var my = (points(i - 1) + points(i)) / 2
                    ctx.quadraticCurveTo(px(i - 1), points(i - 1), mx, my)
                }
                // заливка под линией
                ctx.lineTo(w, baseline)
                ctx.lineTo(-off, baseline)
                ctx.closePath()
                var fill = ctx.createLinearGradient(0, 0, 0, h)
                fill.addColorStop(0.0, Qt.rgba(color.r, color.g, color.b, root.active ? fillAlpha : 0.03))
                fill.addColorStop(1.0, Qt.rgba(color.r, color.g, color.b, 0.0))
                ctx.fillStyle = fill
                ctx.fill()
                // линия поверх
                ctx.beginPath()
                ctx.moveTo(px(0), points(0))
                for (var j = 1; j < n; j++) {
                    var mx2 = (px(j - 1) + px(j)) / 2
                    var my2 = (points(j - 1) + points(j)) / 2
                    ctx.quadraticCurveTo(px(j - 1), points(j - 1), mx2, my2)
                }
                ctx.lineWidth = 2.0
                ctx.lineCap = "round"
                ctx.lineJoin = "round"
                ctx.strokeStyle = root.active ? color : Theme.waveIdle
                ctx.stroke()
            }

            // upload сначала (тоньше / прозрачнее), потом download поверх
            drawLayer(pyU, Theme.accent, 0.10)
            drawLayer(pyD, Theme.teal,   0.22)
        }
    }
}
