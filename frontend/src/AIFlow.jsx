import React, { useCallback } from 'react';
import {
  ReactFlow,
  MiniMap,
  Controls,
  Background,
  useNodesState,
  useEdgesState,
  Handle,
  Position,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { Zap, Bot, BrainCircuit, Database, LineChart, Send, Rss } from 'lucide-react';

const TriggerNode = ({ data }) => (
  <div style={{ background: 'var(--bg-2)', border: '1px solid var(--border)', borderRadius: '8px', padding: '1rem', display: 'flex', alignItems: 'center', gap: '0.75rem', minWidth: '180px', boxShadow: '0 4px 12px rgba(0,0,0,0.5)' }}>
    <div style={{ background: 'rgba(244,63,94,0.1)', padding: '0.5rem', borderRadius: '8px', display: 'flex', color: 'var(--red)' }}>
      <Zap size={20} />
    </div>
    <div>
      <div style={{ fontSize: '0.8rem', fontWeight: 700, color: '#fff' }}>{data.label}</div>
      <div style={{ fontSize: '0.65rem', color: 'var(--text-muted)' }}>Market Event</div>
    </div>
    <Handle type="source" position={Position.Right} style={{ background: '#555', border: 'none', width: '8px', height: '8px' }} />
  </div>
);

const AgentNode = ({ data }) => (
  <div style={{ background: 'rgba(16,185,129,0.05)', border: '1px solid var(--green)', borderRadius: '8px', minWidth: '250px', boxShadow: '0 0 20px rgba(16,185,129,0.15)' }}>
    <Handle type="target" position={Position.Left} id="trigger" style={{ background: '#555', border: 'none', width: '8px', height: '8px' }} />
    <div style={{ padding: '1rem', display: 'flex', alignItems: 'center', gap: '1rem', borderBottom: '1px solid rgba(16,185,129,0.2)' }}>
      <div style={{ background: 'var(--green)', padding: '0.5rem', borderRadius: '8px', color: '#000', display: 'flex' }}>
        <Bot size={24} />
      </div>
      <div>
        <div style={{ fontSize: '1rem', fontWeight: 800, color: '#fff' }}>{data.label}</div>
        <div style={{ fontSize: '0.7rem', color: '#10b981', fontWeight: 600 }}>Tools Agent</div>
      </div>
    </div>
    <div style={{ display: 'flex', justifyContent: 'space-between', padding: '0.5rem 1rem', background: 'rgba(0,0,0,0.3)', borderRadius: '0 0 8px 8px' }}>
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '0.2rem' }}>
        <Handle type="source" position={Position.Bottom} id="model" style={{ position: 'relative', transform: 'none', left: 0, background: '#8b5cf6', width: '6px', height: '6px', border: 'none' }} />
        <span style={{ fontSize: '0.55rem', color: '#8b5cf6', fontWeight: 600 }}>Model</span>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '0.2rem' }}>
        <Handle type="source" position={Position.Bottom} id="memory" style={{ position: 'relative', transform: 'none', left: 0, background: '#3b82f6', width: '6px', height: '6px', border: 'none' }} />
        <span style={{ fontSize: '0.55rem', color: '#3b82f6', fontWeight: 600 }}>Memory</span>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '0.2rem' }}>
        <Handle type="source" position={Position.Bottom} id="tools" style={{ position: 'relative', transform: 'none', left: 0, background: '#f59e0b', width: '6px', height: '6px', border: 'none' }} />
        <span style={{ fontSize: '0.55rem', color: '#f59e0b', fontWeight: 600 }}>Tools</span>
      </div>
    </div>
    <Handle type="source" position={Position.Right} id="output" style={{ background: '#555', border: 'none', width: '8px', height: '8px' }} />
  </div>
);

const ModelNode = ({ data }) => (
  <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '0.5rem' }}>
    <Handle type="target" position={Position.Top} style={{ background: '#8b5cf6', border: 'none', width: '6px', height: '6px' }} />
    <div style={{ width: '60px', height: '60px', borderRadius: '50%', background: 'rgba(139,92,246,0.1)', border: '1px solid #8b5cf6', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#8b5cf6' }}>
      <BrainCircuit size={28} />
    </div>
    <div style={{ fontSize: '0.7rem', color: '#fff', fontWeight: 600, textAlign: 'center' }}>{data.label}</div>
    <div style={{ fontSize: '0.6rem', color: 'var(--text-muted)' }}>{data.sub}</div>
  </div>
);

const MemoryNode = ({ data }) => (
  <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '0.5rem' }}>
    <Handle type="target" position={Position.Top} style={{ background: '#3b82f6', border: 'none', width: '6px', height: '6px' }} />
    <div style={{ width: '60px', height: '60px', borderRadius: '50%', background: 'rgba(59,130,246,0.1)', border: '1px solid #3b82f6', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#3b82f6' }}>
      <Database size={28} />
    </div>
    <div style={{ fontSize: '0.7rem', color: '#fff', fontWeight: 600, textAlign: 'center' }}>{data.label}</div>
    <div style={{ fontSize: '0.6rem', color: 'var(--text-muted)' }}>{data.sub}</div>
  </div>
);

const ToolNode = ({ data }) => {
  const Icon = data.icon === 'chart' ? LineChart : data.icon === 'order' ? Send : Rss;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '0.5rem' }}>
      <Handle type="target" position={Position.Top} style={{ background: '#f59e0b', border: 'none', width: '6px', height: '6px' }} />
      <div style={{ width: '60px', height: '60px', borderRadius: '50%', background: 'rgba(245,158,11,0.1)', border: '1px solid #f59e0b', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#f59e0b' }}>
        <Icon size={24} />
      </div>
      <div style={{ fontSize: '0.7rem', color: '#fff', fontWeight: 600, textAlign: 'center' }}>{data.label}</div>
      <div style={{ fontSize: '0.6rem', color: 'var(--text-muted)' }}>{data.sub}</div>
    </div>
  );
};

const nodeTypes = {
  trigger: TriggerNode,
  agent: AgentNode,
  model: ModelNode,
  memory: MemoryNode,
  tool: ToolNode,
};

const initialNodes = [
  { id: '1', type: 'trigger', position: { x: 50, y: 100 }, data: { label: 'Sinal B3 / Crypto' } },
  { id: '2', type: 'agent', position: { x: 350, y: 70 }, data: { label: 'AI Agent (Criador)' } },
  { id: '3', type: 'model', position: { x: 200, y: 300 }, data: { label: 'Gemini 1.5 Flash', sub: 'Chat Model' } },
  { id: '4', type: 'memory', position: { x: 350, y: 300 }, data: { label: 'Vector DB', sub: 'Sem memória vetorial' } },
  { id: '5', type: 'tool', position: { x: 500, y: 300 }, data: { label: 'Análise Técnica', sub: 'read: market', icon: 'chart' } },
  { id: '6', type: 'tool', position: { x: 650, y: 300 }, data: { label: 'Simulador SQLite', sub: 'paper: order', icon: 'order' } },
];

const initialEdges = [
  { id: 'e1-2', source: '1', target: '2', type: 'smoothstep', animated: true, style: { stroke: '#cbd5e1', strokeWidth: 2 } },
  { id: 'e2-3', source: '2', sourceHandle: 'model', target: '3', type: 'bezier', animated: true, style: { stroke: '#8b5cf6', strokeWidth: 2, strokeDasharray: '5,5' } },
  { id: 'e2-4', source: '2', sourceHandle: 'memory', target: '4', type: 'bezier', animated: true, style: { stroke: '#3b82f6', strokeWidth: 2, strokeDasharray: '5,5' } },
  { id: 'e2-5', source: '2', sourceHandle: 'tools', target: '5', type: 'bezier', animated: true, style: { stroke: '#f59e0b', strokeWidth: 2, strokeDasharray: '5,5' } },
  { id: 'e2-6', source: '2', sourceHandle: 'tools', target: '6', type: 'bezier', animated: true, style: { stroke: '#f59e0b', strokeWidth: 2, strokeDasharray: '5,5' } },
];

export default function AIFlow() {
  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);

  return (
    <div style={{ width: '100%', height: '450px', background: '#0a0a0a', borderRadius: '8px', border: '1px solid var(--border)' }}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        nodeTypes={nodeTypes}
        fitView
        colorMode="dark"
      >
        <Background color="#333" gap={16} />
        <Controls />
      </ReactFlow>
    </div>
  );
}
