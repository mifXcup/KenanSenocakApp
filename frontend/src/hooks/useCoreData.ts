import { useQuery } from '@tanstack/react-query'
import { apiRequest } from '../lib/api'
import type { Material, Payment, Project, Purchase, Supplier } from '../lib/types'

export const queryKeys = {
  suppliers: ['suppliers'] as const,
  materials: ['materials'] as const,
  projects: ['projects'] as const,
  purchases: ['purchases'] as const,
  payments: ['payments'] as const,
  reports: ['reports'] as const,
  backupStatus: ['backup-status'] as const,
  backups: ['backups'] as const,
}

export function useCoreData() {
  const suppliers = useQuery({ queryKey: queryKeys.suppliers, queryFn: () => apiRequest<Supplier[]>('/api/v1/suppliers') })
  const materials = useQuery({ queryKey: queryKeys.materials, queryFn: () => apiRequest<Material[]>('/api/v1/materials') })
  const projects = useQuery({ queryKey: queryKeys.projects, queryFn: () => apiRequest<Project[]>('/api/v1/projects') })
  const purchases = useQuery({ queryKey: queryKeys.purchases, queryFn: () => apiRequest<Purchase[]>('/api/v1/purchases') })
  const payments = useQuery({ queryKey: queryKeys.payments, queryFn: () => apiRequest<Payment[]>('/api/v1/payments') })
  return { suppliers, materials, projects, purchases, payments }
}
