#!/usr/bin/env bash
# Verify all key JS functions exist in templates/index.html with correct signatures
# Usage: bash scripts/verify-functions.sh [path-to-index.html]
FILE="${1:-D:/stock-analysis-system/templates/index.html}"
PASS=0; FAIL=0
check() { local label="$1" pattern="$2"
  if grep -q "$pattern" "$FILE"; then echo "  PASS: $label"; PASS=$((PASS+1))
  else echo "  FAIL: $label"; FAIL=$((FAIL+1)); fi
}

echo "=== Function existence checks ==="
check "resolveStockCode"            'async function resolveStockCode'
check "onFinPeriodChange"           'function onFinPeriodChange'
check "onBsPeriodChange"            'function onBsPeriodChange'
check "loadFinancials (period)"     'const period = document.getElementById..finPeriod'
check "loadFinancials (resolveCmp)" 'cmpCode = await resolveStockCode'
check "loadFinancials (4-arg call)" 'renderFinancialsTable(data, cmpData, cmpCode, cmpName'
check "loadBalanceSheet (period)"   'const period = document.getElementById..bsPeriod'
check "loadBalanceSheet (4-arg)"    'renderBalanceSheetTable(data, cmpData, cmpCode, cmpName'
check "renderFinancialsTable (sig)" 'function renderFinancialsTable(data, cmpData, cmpCode, cmpName'
check "renderFinancialsTable (fmt)" 'const fmtVal = (v, ind)'
check "renderFinancialsTable (yoy)" 'const yoyClass = (y)'
check "renderFinancialsTable (yoyFmt)" 'const yoyFmt = (y)'
check "renderFinancialsTable (q-detect)" 'isQuarterly = true; break'
check "renderFinancialsTable (key)" 'const makeKey = (d)'
check "renderFinancialsTable (prevKey)" 'const makePrevKey = (key)'
check "renderFinancialsTable (cmp-style)" '#fff7e6;color:#fa8c16'
check "renderFinancialsTable (sort-hide)" 'btnSort.style.display = (!isQuarterly'
check "renderFinancialsTable (_finKeys)" '_finKeys = keys'
check "renderFinancialsTable (_finCmp)"   '_finCmpDataMap = cmpDataMap'
check "renderBalanceSheetTable (sig)" 'function renderBalanceSheetTable(data, cmpData, cmpCode, cmpName'
check "renderBalanceSheetTable (cmp)" '#fff7e6'
check "renderBalanceSheetTable (_bsCmp)" '_bsCmpDataMap = cmpDataMap'
check "openBSChart (cmp-orange)"   '#fa8c16'
check "openBSChart (yoy-green)"    '#52c41a'
check "openBSChart (CAGR)"         'cagr = (Math.pow'
check "openBSChart (dual-Y)"       'yAxis: \['
check "openBSChart (dual-Y-split)" 'splitLine: { show: false'
check "openIndicatorChart (keys)"  'const keys = window._finKeys'
check "openIndicatorChart (cmpV)"  'cmpValues = keys.map'
check "isQuarterlyChart fn"        'function isQuarterlyChart'
check "lookupStock (search)"       'stock-search?q='
check "lookupStock (set code)"     "inputCode...value = s.code"
check "loadDetail (curYear)"       'const curYear = new Date().getFullYear()'
check "loadDetail (list_date)"     'stock.list_date'
check "loadDetail (finFromYear)"   "finFromYear...value = startYear"
check "loadDetail (bsToYear)"      "bsToYear...value = curYear"

echo ""
echo "=== Structural integrity ==="
CO=$(grep -o '{' "$FILE" | wc -l); CC=$(grep -o '}' "$FILE" | wc -l)
PO=$(grep -o '(' "$FILE" | wc -l); PC=$(grep -o ')' "$FILE" | wc -l)
echo "  Curly:  open=$CO close=$CC  $( [ "$CO" -eq "$CC" ] && echo OK || echo MISMATCH )"
echo "  Parens: open=$PO close=$PC  $( [ "$PO" -eq "$PC" ] && echo OK || echo MISMATCH )"
[ "$CO" -ne "$CC" ] && FAIL=$((FAIL+1))
[ "$PO" -ne "$PC" ] && FAIL=$((FAIL+1))

echo ""
echo "=== Summary: $PASS passed, $FAIL failed ==="
[ "$FAIL" -eq 0 ] && echo "SUCCESS" || echo "FAILURE"
exit $FAIL
