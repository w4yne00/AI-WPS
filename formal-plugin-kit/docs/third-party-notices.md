# Third-Party Notices — Ribbon Assets

AI-WPS vendors the following two Fluent System Icons as local, offline Ribbon PNG assets. The target WPS host does not fetch these resources at runtime.

## Microsoft Fluent System Icons

- Upstream repository: `https://github.com/microsoft/fluentui-system-icons`
- Pinned commit: `84e8a2ae0e55b3cbe176b5cc33154fe82ef363cc` (`1.1.337`, published 2026-08-13)
- License: MIT
- Copyright: `Copyright (c) 2020 Microsoft Corporation`
- License text: `https://github.com/microsoft/fluentui-system-icons/blob/84e8a2ae0e55b3cbe176b5cc33154fe82ef363cc/LICENSE`

### Excel formula assistant

- Asset: `Math Formula 32 Regular`
- Upstream path: `assets/Math Formula/SVG/ic_fluent_math_formula_32_regular.svg`
- Source URL: `https://raw.githubusercontent.com/microsoft/fluentui-system-icons/84e8a2ae0e55b3cbe176b5cc33154fe82ef363cc/assets/Math%20Formula/SVG/ic_fluent_math_formula_32_regular.svg`
- Original SVG SHA-256: `cad595404d908e24d7b0020566f1905b1cfb4208850865a6abce1a0ed43072ad`
- Equivalent pinned PDF render source: `assets/Math Formula/PDF/ic_fluent_math_formula_32_regular.pdf`
- PDF render source SHA-256: `18a2c94a8c8bfc2cd448f3602baa74834b6724ee0bdfe0c26dfb1b4eeda45149`
- Distributed asset: `packages/wps-ai-assistant-et_1.0.0/assets/icon-excel-formula-assistant.png`
- Derived PNG SHA-256: `76a38eb6a820300df70d080b44c1a1c097f61f82ff5d2c3ffded895c0da018f8`
- Local transformation: rasterized the pinned 32×32 upstream vector asset at 72 DPI, removed the rasterizer's white background by deriving alpha from the grayscale coverage, and recolored the antialiased glyph to the existing Excel accent `#426FA8`; no runtime dependency was added.

### PPT structure review

- Asset: `Slide Text Multiple 32 Regular`
- Upstream path: `assets/Slide Text Multiple/SVG/ic_fluent_slide_text_multiple_32_regular.svg`
- Source URL: `https://raw.githubusercontent.com/microsoft/fluentui-system-icons/84e8a2ae0e55b3cbe176b5cc33154fe82ef363cc/assets/Slide%20Text%20Multiple/SVG/ic_fluent_slide_text_multiple_32_regular.svg`
- Original SVG SHA-256: `d114582e08edb434a1acc921269fb230a3159958b76f4d52bdc66f127efbe921`
- Equivalent pinned PDF render source: `assets/Slide Text Multiple/PDF/ic_fluent_slide_text_multiple_32_regular.pdf`
- PDF render source SHA-256: `86cf017352677b9f8a2e6378bfef2f1a6990333398ebfd04bf9c202c272ee2a5`
- Distributed asset: `packages/wps-ai-assistant-wpp_1.0.0/assets/icon-ppt-structure-review.png`
- Derived PNG SHA-256: `7059d8f4f61d4c5f29503c8e89f8f4f4e355bacc1052994266f8cc92500ae70b`
- Local transformation: rasterized the pinned 32×32 upstream vector asset at 72 DPI, removed the rasterizer's white background by deriving alpha from the grayscale coverage, and recolored the antialiased glyph to the existing PPT accent `#386EA8`; no runtime dependency was added.

The upstream MIT notice is reproduced here for the distributed substantial portions:

> MIT License
>
> Copyright (c) 2020 Microsoft Corporation
>
> Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:
>
> The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.
>
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
