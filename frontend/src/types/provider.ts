/**
 * Provider, Worker, and Loadout contracts for the frontend client.
 */

import { AgentRole } from './agent';

export interface Provider {
  id: string; // 'groq', 'gemini', 'openrouter'
  name: string;
  baseUrl: string;
  supportsStreaming: boolean;
  supportsToolCalling: boolean;
  isActive: boolean;
  createdAt: string;
}

export interface Credential {
  id: string;
  userId: string;
  providerId: string;
  keyFingerprint: string;
  createdAt: string;
  updatedAt: string;
}

export interface Worker {
  id: string;
  providerId: string;
  modelName: string;
  contextWindowTokens: number;
  maxOutputTokens: number;
  temperature: number;
  rateLimitRpm?: number;
  rateLimitTpm?: number;
  createdAt: string;
}

export interface AgentWorkerMapping {
  primaryWorkerId: string;
  fallbackWorkerIds: string[];
}

export interface Loadout {
  id: string;
  userId?: string;
  name: string;
  description?: string;
  isSystemPreset: boolean;
  mappings: Record<AgentRole, AgentWorkerMapping>;
  createdAt: string;
  updatedAt: string;
}

export interface TemporaryOverride {
  taskId: string;
  agentRole: AgentRole;
  targetWorkerId: string;
  reason?: string;
}
