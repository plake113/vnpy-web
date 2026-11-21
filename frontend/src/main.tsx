import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

// 令牌与基础样式必须先于页面样式进入模块图，保证构建产物的声明顺序稳定。
import './styles/tokens.css'
import './styles/base.css'

import App from './App'

const container = document.getElementById('root')
if (!container) {
  throw new Error('未找到 #root 挂载节点')
}

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
