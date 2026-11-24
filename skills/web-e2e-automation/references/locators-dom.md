# Locators and DOM

Accessibility name first. A locator that needs a screenshot to explain is the wrong locator.

## Hierarchy

Use the first one that is unique and stable:

1. Role and accessible name (`getByRole`, `find_element` by accessible name).
2. Label.
3. Placeholder.
4. Text.
5. Alt or title.
6. An explicit `data-testid` the app owns. Do not invent one to dodge a role.
7. One semantic CSS attribute (`[type="submit"]`, `[href="/pay"]`). One attribute, not a chain.
8. Scoped relative XPath, last. It starts at a role, test id, or landmark you already hold.

`/html/body` and any XPath that starts at `/html` are defects. Strict mode is the default: a locator that matches two nodes fails. Prefer `filter()` with a role, name, or text. `.first()`, `.nth()`, and `.last()` hide the real node.

## Hard DOM patterns

| Surface | Do | Do not |
| --- | --- | --- |
| Open shadow DOM | Pierce from the host (`locator` pierce, or the open shadow root) and use the hierarchy inside | Copy generated class names from the shadow tree |
| Closed shadow DOM | Drive the host's public role, test id, or app test hook | Reach through a closed root |
| Nested iframes | `frameLocator` (or frame switch) per hop, then the hierarchy inside that frame | One locator from the top document into the inner frame |
| Cross-origin iframes | Stay on that frame's origin, or use the app's test hook | Scrape the other origin |
| Virtualized lists and tables | Scroll the scroller and assert the rendered window plus the data length from the app | Treat DOM row count as the list length |
| React, Angular, Vue hydration | Wait on a role or an app-ready locator | Sleep, or assert pre-hydration markup |
| Portals, modals, toasts | Scope to `dialog`, `alertdialog`, or `status` | A path from `body` through the portal host |
| SVG | Role, `<title>`, or the host button's name | `nth` of a `<path>` |
| Canvas and WebGL | Accessible status, exported scene state, or a test hook | A full pixel or `outerHTML` dump as the oracle |

## Objects

Component objects plus fixtures are the default. One object per region the user can name. Actions do one thing and return the next component or a value. Assertions stay in the test. Fixtures own the browser context, storage, and routes.

A god page object that can click every control on every page is a defect. Screenplay (actor, task, question) earns that indirection only when several actors share a large task catalog and page objects have already turned into a god object. A single user journey does not earn it.

## Page source and the accessibility tree

Prefer a scoped accessibility snapshot over markup:

- Playwright `ariaSnapshot()` on the locator that owns the region.
- `playwright-cli snapshot "#main"`, with `--depth` when the tree is deep, then `find` on the saved snapshot.

Geometry and computed style, when the turn really needs them, are targeted reads on that node. The viewport x theme matrix and red-then-green UI proof stay in `references/ui-delivery.md`.

Do not put `page.content()`, `getPageSource()`, `.page_source`, or `document.documentElement.outerHTML` into the model context. A full document is an unbounded prompt, not a locator.
