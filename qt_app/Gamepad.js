.pragma library

var openCombo = null
function trackCombo(control) { openCombo=control }

function handleCombo(action) {
    if (!openCombo || !openCombo.choosing) { openCombo=null; return false }
    return openCombo.navigateChoice(action)
}

function controls(root) {
    let found = []
    function visit(item) {
        if (!item || !item.visible || !item.enabled) return
        if (item.gamepadFocusable === true) { found.push(item); return }
        for (let child of item.children || []) visit(child)
    }
    visit(root)
    return found
}

function navigate(root, focused, direction, adjustSliders) {
    let items = controls(root)
    if (!items.length) return
    let current = items.find(item => item === focused || item.activeFocus)
    if (!current) { items[0].forceActiveFocus(); return }
    if (adjustSliders !== false && current.gamepadKind === "slider" && (direction === "left" || direction === "right")) {
        current.value=Math.max(current.from, Math.min(current.to, current.value+(direction === "right" ? 1 : -1)*current.stepSize))
        return
    }
    let origin = current.mapToItem(root, current.width/2, current.height/2)
    let best = null, score = Infinity
    for (let item of items) {
        if (item === current) continue
        let point = item.mapToItem(root, item.width/2, item.height/2)
        let dx = point.x-origin.x, dy = point.y-origin.y
        let forward = direction === "left" ? -dx : direction === "right" ? dx : direction === "up" ? -dy : dy
        let cross = direction === "left" || direction === "right" ? Math.abs(dy) : Math.abs(dx)
        if (forward <= 2) continue
        let cost = forward + cross*4
        if (cost < score) { score=cost; best=item }
    }
    if (best) {
        best.forceActiveFocus()
        let ancestor=best.parent
        while (ancestor) {
            if (ancestor.contentY !== undefined && ancestor.contentItem) {
                let position=best.mapToItem(ancestor.contentItem,0,0)
                if (position.y < ancestor.contentY) ancestor.contentY=position.y
                else if (position.y+best.height > ancestor.contentY+ancestor.height) ancestor.contentY=position.y+best.height-ancestor.height
            }
            ancestor=ancestor.parent
        }
    }
}

function activate(root, focused, keyboard) {
    let item = controls(root).find(control => control === focused || control.activeFocus)
    if (!item) return
    if (item.gamepadKind === "text") keyboard.openFor(item)
    else if (item.gamepadKind === "combo") {
        if (!item.count) return
        openCombo=item
        item.openChoices()
    } else if (item.gamepadKind === "check") { item.checked = !item.checked; item.toggled() }
    else if (item.clicked) item.clicked()
}
