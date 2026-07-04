# JS Template Literal 嵌套引号陷阱

## 症状

- 网络请求正常（API 返回 200）
- 页面空白、\"加载中\"卡死
- 浏览器控制台报 `SyntaxError: missing ) after argument list`
- `loadStats is not defined` 等全局函数丢失

## 根因

Template literal（反引号字符串）内嵌多层引号转义时，浏览器 JS 解析器可能产生语法错误。

**错误示例**（在 template literal 内部）：
```javascript
// index.html 模板字面量内
'<img onerror="this.outerHTML=\\\\'<span>fallback</span>\\\\'">'
// 四层转义（template literal → JS string → HTML attribute → JS in HTML）
// → SyntaxError: missing ) after argument list
```

转义层级：
1. **HTML 层**：`\"` → `"`
2. **JS 字符串层**：`\\'` → `\'`
3. **HTML 属性内 JS**：`\'` → `'`

在 template literal 中，`\\` 和 `\'` 的交互会导致不可预测的转义行为。

## 修复

**永远不要在 template literal 内使用超过两层的引号转义**。

```javascript
// ✅ 正确：只做 display:none
'<img onerror="this.style.display=\\\'none\\\'">'

// ✅ 更好：完全不嵌套 JS
'<img onerror="this.style.display=none">'
```

如果 img 加载失败需要显示回退文字，用 CSS 伪元素或 alt 属性，不要用 `outerHTML` 动态替换 DOM。

## 检测方法

1. Chrome DevTools → 确认所有 API 请求 200
2. 手动 `eval(document.querySelector('script:not([src])').textContent)` → 捕获语法错误
3. 用 curl 抓取页面，搜索疑似多层转义的行（`\\\\\\\\'` 等）
