import { formatDate, formatMoney } from './lib/api'
import { Button } from './components/ui'

export interface CashReceiptData {
  movementId: string
  employeeName: string
  identityNumber: string
  periodTitle: string
  paymentDate: string
  amountKurus: number
  beforeKurus: number
  afterKurus: number
}

export function CashReceipt({ receipt }: { receipt: CashReceiptData }) {
  return <section className="cash-receipt-wrap">
    <div className="cash-receipt-actions"><strong>Elden ödeme teslim belgesi hazır</strong><Button onClick={() => window.print()}>Yazdır / PDF kaydet</Button></div>
    <article className="cash-receipt" aria-label="Elden ücret ödeme teslim belgesi">
      <h1>Elden Ücret Ödeme Teslim Belgesi</h1>
      <p>Belge no: {receipt.movementId}</p>
      <p>Ödeme tarihi: {formatDate(receipt.paymentDate)}</p>
      <p>İlgili maaş dönemi: {receipt.periodTitle}</p>
      <div className="cash-receipt-grid"><span>Çalışanın adı soyadı</span><strong>{receipt.employeeName}</strong><span>T.C. kimlik numarası</span><strong>{receipt.identityNumber}</strong><span>Ödeme öncesi kalan ücret</span><strong>{formatMoney(receipt.beforeKurus)}</strong><span>Elden teslim alınan tutar</span><strong>{formatMoney(receipt.amountKurus)}</strong><span>Ödeme sonrası kalan ücret</span><strong>{formatMoney(receipt.afterKurus)}</strong></div>
      <p className="cash-receipt-statement">Yukarıda belirtilen {formatMoney(receipt.amountKurus)} tutarı {formatDate(receipt.paymentDate)} tarihinde nakit olarak teslim aldım. Bu belge yalnız belirtilen ödemenin teslimini ve kayıt anındaki kalan tutarı gösterir; diğer ücret ve yasal haklara ilişkin ibra beyanı içermez.</p>
      <div className="cash-receipt-signatures"><div>Çalışan adı soyadı / imza</div><div>İşveren yetkilisi adı soyadı / imza</div></div>
      <small>İki nüsha düzenlenir; bir nüshası çalışana verilir. İmzalı nüshayı güvenli biçimde saklayın.</small>
      <p className="cash-receipt-legal">Bu belge, uygulanıyorsa ücretin banka aracılığıyla ödenmesi yükümlülüğünün yerine geçmez.</p>
    </article>
  </section>
}
