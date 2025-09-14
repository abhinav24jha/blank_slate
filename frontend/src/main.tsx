import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import HacktheNorthUI from './HacktheNorthUI.tsx'


createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <HacktheNorthUI />
  </StrictMode>,
)
