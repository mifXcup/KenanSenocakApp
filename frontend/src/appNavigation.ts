import type { Icon } from '@phosphor-icons/react'
import {
  AddressBook,
  Buildings,
  CalendarCheck,
  CalendarDots,
  ChartBar,
  ChartLineUp,
  GearSix,
  House,
  IdentificationCard,
  Package,
  Receipt,
  Sparkle,
  Storefront,
  Wallet,
} from '@phosphor-icons/react'

export interface NavigationItem {
  to: string
  label: string
  icon: Icon
  contractPending?: boolean
}

export interface NavigationGroup {
  label: string
  items: NavigationItem[]
}

export const navigationGroups: NavigationGroup[] = [
  {
    label: 'Operasyon',
    items: [
      { to: '/', label: 'Bugün', icon: House },
      { to: '/takvim', label: 'Takvim', icon: CalendarDots, contractPending: true },
      { to: '/projeler', label: 'Projeler', icon: Buildings },
    ],
  },
  {
    label: 'Finans',
    items: [
      { to: '/proje-karliligi', label: 'Proje Kârlılığı', icon: ChartLineUp, contractPending: true },
      { to: '/musteriler', label: 'Müşteri Cari', icon: AddressBook, contractPending: true },
      { to: '/firmalar', label: 'Tedarikçi Cari', icon: Storefront },
      { to: '/satin-almalar', label: 'Satın Almalar', icon: Receipt },
      { to: '/malzemeler', label: 'Malzemeler', icon: Package },
    ],
  },
  {
    label: 'Personel',
    items: [
      { to: '/personel', label: 'Personel', icon: IdentificationCard },
      { to: '/puantaj-izin', label: 'Puantaj ve İzin', icon: CalendarCheck, contractPending: true },
      { to: '/maas-donemleri', label: 'Maaş Dönemleri', icon: Wallet, contractPending: true },
    ],
  },
  {
    label: 'Analiz',
    items: [
      { to: '/raporlar', label: 'Raporlar', icon: ChartBar },
      { to: '/akilli-ongoruler', label: 'Akıllı Öngörüler', icon: Sparkle },
    ],
  },
  {
    label: 'Sistem',
    items: [
      { to: '/ayarlar', label: 'Veri ve Ayarlar', icon: GearSix },
    ],
  },
]

export const navigationItems = navigationGroups.flatMap((group) => group.items)

export function navigationLabel(pathname: string): string {
  return navigationItems.find((item) => item.to === pathname)?.label ?? 'Kenan Şenocak Yönetim'
}

