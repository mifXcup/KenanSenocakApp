import type { Icon } from '@phosphor-icons/react'
import { CalendarCheck, CalendarDots, ChartLineUp, IdentificationCard, Wallet } from '@phosphor-icons/react'
import { PageHeader, StatusBanner } from './components/ui'

interface FoundationPageProps {
  eyebrow: string
  title: string
  description: string
  icon: Icon
  capabilities: string[]
}

function FoundationPage({ eyebrow, title, description, icon: Icon, capabilities }: FoundationPageProps) {
  return (
    <div className="page foundation-page">
      <PageHeader title={title} description={description} />
      <StatusBanner>Veri sözleşmesi backend dalında uygulanıyor. Bu ekran henüz canlı finansal kayıt üretmez.</StatusBanner>
      <section className="foundation-card" aria-labelledby="foundation-title">
        <div className="foundation-card__icon"><Icon size={24} aria-hidden="true" /></div>
        <div>
          <span className="foundation-card__eyebrow">{eyebrow}</span>
          <h2 id="foundation-title">Hazırlanan kapsam</h2>
          <p>Backend kontratı kesinleştiğinde aşağıdaki işlevler aynı sayfa yapısına bağlanacak.</p>
        </div>
        <ul>{capabilities.map((capability) => <li key={capability}>{capability}</li>)}</ul>
      </section>
    </div>
  )
}

export function CalendarFoundationPage() {
  return <FoundationPage eyebrow="OPERASYON" title="Takvim" description="Görev, tahsilat, ödeme, maaş ve izinleri tek zaman akışında yönetin." icon={CalendarDots} capabilities={['Ay, hafta ve gündem görünümü', 'Gecikmiş, bugün ve yaklaşan işler', 'Kaynak kayda geçiş ve Windows bildirimi']} />
}

export function ProfitabilityFoundationPage() {
  return <FoundationPage eyebrow="FİNANS" title="Proje Kârlılığı" description="Bütçe, taahhüt, gerçekleşen ve bitirme tahminini birlikte izleyin." icon={ChartLineUp} capabilities={['Kategori bazlı bütçe ve sapma', 'Tahmini bitirme maliyeti ve kâr marjı', 'Her toplamdan kaynak harekete detay açılım']} />
}

export function CustomersFoundationPage() {
  return <FoundationPage eyebrow="FİNANS" title="Müşteri Cari" description="Sözleşme, hakediş, tahsilat ve kalan alacağı proje bağlamında izleyin." icon={IdentificationCard} capabilities={['Müşteri kartı ve bağlı projeler', 'Tahsilat planı ve kısmi tahsilat', 'Ekstre, yaşlandırma ve ters kayıt']} />
}

export function AttendanceFoundationPage() {
  return <FoundationPage eyebrow="PERSONEL" title="Puantaj ve İzin" description="Günlük devamı, mesaiyi ve izin bakiyelerini aylık çizelgeden yönetin." icon={CalendarCheck} capabilities={['Aylık toplu puantaj ızgarası', 'İzin hakkı, onay ve bakiye defteri', 'Eksik veya çakışan kayıt denetimi']} />
}

export function PayrollFoundationPage() {
  return <FoundationPage eyebrow="PERSONEL" title="Maaş Dönemleri" description="Maaş hesabını kontrol edin, kesinleştirin, ödeyin ve dönemi kapatın." icon={Wallet} capabilities={['Hesapla, kontrol et, kesinleştir ve kapat', 'Avans, borç, kesinti ve ek kazanç', 'Kısmi ödeme, kalan borç ve dışa aktarma']} />
}

