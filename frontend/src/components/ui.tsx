import { cloneElement, useId, useRef, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactElement, type ReactNode, type SelectHTMLAttributes } from 'react'
import { CheckCircle, Info, SpinnerGap, WarningCircle, X } from '@phosphor-icons/react'
import type { TrackingMode } from '../lib/types'
import { formatMoney } from '../lib/api'
import { useDialogFocus } from '../hooks/useDialogFocus'

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'secondary' | 'quiet' | 'danger'
  loading?: boolean
}

export function Button({ variant = 'secondary', loading, className = '', children, disabled, ...props }: ButtonProps) {
  return (
    <button className={`button button--${variant} ${className}`} disabled={disabled || loading} {...props}>
      {loading && <SpinnerGap aria-hidden="true" className="spin" size={18} />}
      {children}
    </button>
  )
}

export function PageHeader({ title, description, action }: { title: string; description: string; action?: ReactNode }) {
  return (
    <header className="page-header">
      <div>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {action && <div className="page-header__action">{action}</div>}
    </header>
  )
}

export function MoneyValue({ value, emphasis = false }: { value?: number | null; emphasis?: boolean }) {
  return <span className={`money ${emphasis ? 'money--emphasis' : ''}`}>{formatMoney(value)}</span>
}

const confidenceLabels: Record<TrackingMode, string> = {
  exact: 'Kesin',
  estimated: 'Yaklaşık',
  value_only: 'Yalnız tutar',
}

export function ConfidenceBadge({ mode }: { mode: TrackingMode }) {
  return (
    <span className={`badge badge--${mode}`}>
      {mode === 'exact' ? <CheckCircle size={14} /> : mode === 'estimated' ? <WarningCircle size={14} /> : <Info size={14} />}
      {confidenceLabels[mode]}
    </span>
  )
}

export function EmptyState({ title, description, action }: { title: string; description: string; action?: ReactNode }) {
  return (
    <div className="empty-state">
      <div className="empty-state__mark" aria-hidden="true" />
      <h2>{title}</h2>
      <p>{description}</p>
      {action}
    </div>
  )
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const message = error instanceof Error ? error.message : 'Beklenmeyen bir hata oluştu.'
  return (
    <div className="status-panel status-panel--error" role="alert">
      <WarningCircle size={22} aria-hidden="true" />
      <div><strong>Veri yüklenemedi</strong><p>{message}</p></div>
      {onRetry && <Button onClick={onRetry}>Yeniden dene</Button>}
    </div>
  )
}

export function LoadingRows({ count = 5 }: { count?: number }) {
  return <div className="skeleton-list" aria-label="Yükleniyor">{Array.from({ length: count }, (_, index) => <div className="skeleton-row" key={index} />)}</div>
}

export function StatusBanner({ children }: { children: ReactNode }) {
  return <div className="status-banner" role="status"><Info size={18} aria-hidden="true" />{children}</div>
}

export function Field({ label, hint, error, children }: { label: string; hint?: string; error?: string; children: ReactNode }) {
  const generatedControlId = useId()
  const descriptionId = useId()
  const child = children as ReactElement<{ id?: string; 'aria-describedby'?: string; 'aria-invalid'?: boolean }>
  const controlId = child.props.id ?? generatedControlId
  const control = cloneElement(child, {
    id: controlId,
    'aria-describedby': hint || error ? descriptionId : undefined,
    'aria-invalid': Boolean(error),
  })
  return (
    <div className="field">
      <label className="field__label" htmlFor={controlId}>{label}</label>
      {control}
      {hint && !error && <span id={descriptionId} className="field__hint">{hint}</span>}
      {error && <span id={descriptionId} className="field__error"><WarningCircle size={14} />{error}</span>}
    </div>
  )
}

export function TextInput(props: InputHTMLAttributes<HTMLInputElement>) {
  return <input className="input" {...props} />
}

export function SelectInput(props: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select className="input" {...props} />
}

export function SideSheet({ title, description, open, onClose, children, footer }: { title: string; description?: string; open: boolean; onClose: () => void; children: ReactNode; footer?: ReactNode }) {
  const dialogRef = useRef<HTMLElement>(null)
  useDialogFocus(open, onClose, dialogRef)
  if (!open) return null
  return (
    <div className="sheet-layer" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <section ref={dialogRef} className="sheet" role="dialog" aria-modal="true" aria-labelledby="sheet-title">
        <header className="sheet__header">
          <div><h2 id="sheet-title">{title}</h2>{description && <p>{description}</p>}</div>
          <button className="icon-button" onClick={onClose} aria-label="Paneli kapat"><X size={20} /></button>
        </header>
        <div className="sheet__body">{children}</div>
        {footer && <footer className="sheet__footer">{footer}</footer>}
      </section>
    </div>
  )
}

export function Modal({ title, description, open, onClose, children, footer }: { title: string; description?: string; open: boolean; onClose: () => void; children: ReactNode; footer?: ReactNode }) {
  const dialogRef = useRef<HTMLElement>(null)
  useDialogFocus(open, onClose, dialogRef)
  if (!open) return null
  return (
    <div className="modal-layer" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <section ref={dialogRef} className="modal" role="alertdialog" aria-modal="true" aria-labelledby="modal-title" aria-describedby={description ? 'modal-description' : undefined}>
        <header className="modal__header">
          <div><h2 id="modal-title">{title}</h2>{description && <p id="modal-description">{description}</p>}</div>
          <button className="icon-button" onClick={onClose} aria-label="Pencereyi kapat"><X size={20} /></button>
        </header>
        <div className="modal__body">{children}</div>
        {footer && <footer className="modal__footer">{footer}</footer>}
      </section>
    </div>
  )
}
