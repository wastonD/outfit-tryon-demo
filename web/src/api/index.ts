import * as real from './client'
import * as mock from './mock'

export * from './types'
export { ApiError, fileUrl } from './client'

const impl = import.meta.env.VITE_MOCK === '1' ? mock : real

export const getStatus = impl.getStatus
export const getMe = impl.getMe
export const getPresets = impl.getPresets
export const submitFeedback = impl.submitFeedback
export const importLink = impl.importLink
export const importImagesFiles = impl.importImagesFiles
export const importImagesJson = impl.importImagesJson
export const listGarments = impl.listGarments
export const getGarment = impl.getGarment
export const patchGarment = impl.patchGarment
export const deleteGarment = impl.deleteGarment
export const reprocessGarment = impl.reprocessGarment
export const createOutfit = impl.createOutfit
export const listOutfits = impl.listOutfits
export const getOutfit = impl.getOutfit
export const deleteOutfit = impl.deleteOutfit
export const createTurntable = impl.createTurntable
export const getJob = impl.getJob
export const retryJob = impl.retryJob
