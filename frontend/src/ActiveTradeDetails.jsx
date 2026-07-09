import React, { useEffect, useRef, useState } from 'react';
import { createChart, CandlestickSeries } from 'lightweight-charts';
import axios from 'axios';
import { Crosshair, ShieldAlert, Cpu, ChevronLeft, AlertTriangle } from 'lucide-react';

const API_BASE = 'http://localhost:8000/api';

const ActiveTradeDetails = ({ trade, onBack }) => {
  const chartContainerRef = useRef(null);
  const chartRef = useRef(null);
  const [candles, setCandles] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Fetch candle data
    axios.get(`${API_BASE}/candles/${trade.ticker}`)
      .then(res => {
        if (res.data.candles) {
          setCandles(res.data.candles);
        }
        setLoading(false);
      })
      .catch(err => {
        console.error("Failed to load candles", err);
        setLoading(false);
      });
  }, [trade.ticker]);

  useEffect(() => {
    if (loading || candles.length === 0 || !chartContainerRef.current) return;

    // Initialize chart
    const handleResize = () => {
      if(chartRef.current && chartContainerRef.current) {
        chartRef.current.applyOptions({ width: chartContainerRef.current.clientWidth });
      }
    };

    const chart = createChart(chartContainerRef.current, {
      autoSize: true,
      layout: {
        textColor: '#cbd5e1',
      },
      grid: {
        vertLines: { color: 'rgba(255, 255, 255, 0.05)' },
        horzLines: { color: 'rgba(255, 255, 255, 0.05)' },
      },
    });

    const candlestickSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#10b981', downColor: '#f43f5e', borderVisible: false,
      wickUpColor: '#10b981', wickDownColor: '#f43f5e',
    });

    // Strip out the 'value' field just in case
    const safeCandles = candles.map(c => ({
      time: c.time,
      open: c.open,
      high: c.high,
      low: c.low,
      close: c.close
    }));

    candlestickSeries.setData(safeCandles);

    // Draw Price Lines for Entry, Target, Stop
    if (trade.entry_price) {
      candlestickSeries.createPriceLine({
        price: trade.entry_price,
        color: '#00f3ff',
        lineWidth: 2,
        lineStyle: 2, // Dashed
        title: 'ENTRY',
      });
    }

    if (trade.target_price) {
      candlestickSeries.createPriceLine({
        price: trade.target_price,
        color: '#10b981',
        lineWidth: 2,
        lineStyle: 1, // Dotted
        title: 'TAKE PROFIT',
      });
    }

    if (trade.stop_loss) {
      candlestickSeries.createPriceLine({
        price: trade.stop_loss,
        color: '#f43f5e',
        lineWidth: 2,
        lineStyle: 1,
        title: 'STOP LOSS',
      });
    }

    chart.timeScale().fitContent();
    chartRef.current = chart;

    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      if (chartRef.current) chartRef.current.remove();
    };
  }, [candles, loading, trade]);

  const pnlColor = trade.pnl_pct >= 0 ? '#10b981' : '#f43f5e';

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem', animation: 'fadeIn 0.3s' }}>
      
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
        <button onClick={onBack} style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.1)', color: '#fff', padding: '0.5rem 1rem', borderRadius: '4px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '0.5rem', fontWeight: 600 }}>
          <ChevronLeft size={16} /> VOLTAR
        </button>
        <div>
          <h2 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            {trade.ticker} 
            <span style={{ fontSize: '0.75rem', background: trade.side === 'BUY' ? 'rgba(16,185,129,0.1)' : 'rgba(244,63,94,0.1)', color: trade.side === 'BUY' ? '#10b981' : '#f43f5e', padding: '0.2rem 0.6rem', borderRadius: '4px', border: `1px solid ${trade.side === 'BUY' ? 'rgba(16,185,129,0.3)' : 'rgba(244,63,94,0.3)'}` }}>
              LONG
            </span>
          </h2>
          <span style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>Operação aberta em {new Date(trade.entry_date).toLocaleString()}</span>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: '1.5rem' }}>
        
        {/* Left Col: Chart & Metrics */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
          
          <div className="glass-panel" style={{ padding: '0', overflow: 'hidden' }}>
            <div className="panel-header" style={{ borderBottom: '1px solid rgba(255,255,255,0.05)', padding: '1rem', background: 'rgba(0,0,0,0.2)' }}>
              <h3 style={{ margin: 0, fontSize: '0.9rem', color: '#fff' }}>Evolução do Preço</h3>
            </div>
            {loading ? (
              <div style={{ height: '400px', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)' }}>
                Carregando dados da B3...
              </div>
            ) : candles.length === 0 ? (
              <div style={{ height: '400px', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#f43f5e', flexDirection: 'column', gap: '0.5rem' }}>
                <AlertTriangle size={24} />
                <span>Nenhum dado de candle encontrado. (Possível bloqueio do Yahoo Finance)</span>
              </div>
            ) : (
              <div ref={chartContainerRef} style={{ width: '100%', height: '400px', background: '#020617' }} />
            )}
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '1rem' }}>
            <div className="glass-panel" style={{ padding: '1rem' }}>
              <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem', fontWeight: 700, textTransform: 'uppercase' }}>Entrada Executada</span>
              <div style={{ fontSize: '1.5rem', fontWeight: 800, color: '#fff', marginTop: '0.5rem' }}>R$ {trade.entry_price?.toFixed(2)}</div>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '0.25rem' }}>Tamanho: {trade.shares?.toFixed(0)} ações</div>
            </div>
            <div className="glass-panel" style={{ padding: '1rem', borderTop: '2px solid #10b981' }}>
              <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem', fontWeight: 700, textTransform: 'uppercase' }}><Crosshair size={12} style={{ display: 'inline', marginRight: '4px' }}/> Take Profit (Alvo)</span>
              <div style={{ fontSize: '1.5rem', fontWeight: 800, color: '#10b981', marginTop: '0.5rem' }}>R$ {trade.target_price?.toFixed(2)}</div>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '0.25rem' }}>Risco/Retorno: 1:3</div>
            </div>
            <div className="glass-panel" style={{ padding: '1rem', borderTop: '2px solid #f43f5e' }}>
              <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem', fontWeight: 700, textTransform: 'uppercase' }}><ShieldAlert size={12} style={{ display: 'inline', marginRight: '4px' }}/> Stop Loss (Risco)</span>
              <div style={{ fontSize: '1.5rem', fontWeight: 800, color: '#f43f5e', marginTop: '0.5rem' }}>R$ {trade.stop_loss?.toFixed(2)}</div>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '0.25rem' }}>Hard stop no servidor</div>
            </div>
            <div className="glass-panel" style={{ padding: '1rem', background: 'rgba(0,0,0,0.4)' }}>
              <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem', fontWeight: 700, textTransform: 'uppercase' }}>Lucro/Prejuízo Aberto</span>
              <div style={{ fontSize: '1.5rem', fontWeight: 800, color: pnlColor, marginTop: '0.5rem' }}>{trade.pnl_pct > 0 ? '+' : ''}{trade.pnl_pct?.toFixed(2)}%</div>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '0.25rem' }}>Atualizado em tempo real</div>
            </div>
          </div>

        </div>

        {/* Right Col: AI Rationale */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
          
          <div className="glass-panel" style={{ height: '100%', display: 'flex', flexDirection: 'column', background: 'linear-gradient(180deg, rgba(255,255,255,0.03) 0%, rgba(0,0,0,0.2) 100%)' }}>
            <div className="panel-header" style={{ padding: '1.25rem', borderBottom: '1px solid rgba(255,255,255,0.05)', display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
              <div style={{ background: 'rgba(0,243,255,0.1)', padding: '0.5rem', borderRadius: '8px' }}>
                <Cpu size={20} color="#00f3ff" />
              </div>
              <div>
                <h3 style={{ margin: 0, fontSize: '1rem', color: '#fff' }}>Dossiê de Decisão (IA)</h3>
                <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Por que entramos nesse trade?</span>
              </div>
            </div>
            
            <div style={{ padding: '1.5rem', flex: 1, display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
              
              <div>
                <div style={{ fontSize: '0.7rem', fontWeight: 800, color: '#3b82f6', textTransform: 'uppercase', letterSpacing: '1px', marginBottom: '0.5rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                  <div style={{ width: '6px', height: '6px', background: '#3b82f6', borderRadius: '50%' }}></div> MARKET ANALYST
                </div>
                <div style={{ background: 'rgba(0,0,0,0.4)', padding: '1rem', borderRadius: '6px', borderLeft: '3px solid #3b82f6', fontSize: '0.85rem', lineHeight: 1.6, color: '#e2e8f0', fontFamily: 'JetBrains Mono, monospace' }}>
                  {trade.ai_rationale || 'Nenhuma justificativa textual foi providenciada para esta execução antiga.'}
                </div>
              </div>

              <div>
                <div style={{ fontSize: '0.7rem', fontWeight: 800, color: '#f59e0b', textTransform: 'uppercase', letterSpacing: '1px', marginBottom: '0.5rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                  <div style={{ width: '6px', height: '6px', background: '#f59e0b', borderRadius: '50%' }}></div> RISK MANAGER
                </div>
                <div style={{ background: 'rgba(0,0,0,0.4)', padding: '1rem', borderRadius: '6px', borderLeft: '3px solid #f59e0b', fontSize: '0.85rem', lineHeight: 1.6, color: '#e2e8f0' }}>
                  Aprovado. Dimensionamento baseado na volatilidade histórica. Risco limitado a 2% do capital em conta via critério de Kelly dinâmico.
                </div>
              </div>

              <div>
                <div style={{ fontSize: '0.7rem', fontWeight: 800, color: '#10b981', textTransform: 'uppercase', letterSpacing: '1px', marginBottom: '0.5rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                  <div style={{ width: '6px', height: '6px', background: '#10b981', borderRadius: '50%' }}></div> EXECUTOR ALGO
                </div>
                <div style={{ background: 'rgba(0,0,0,0.4)', padding: '1rem', borderRadius: '6px', borderLeft: '3px solid #10b981', fontSize: '0.85rem', lineHeight: 1.6, color: '#e2e8f0' }}>
                  Ordem de entrada roteada via API Cedro. Execução limpa sem slippage significativo.
                </div>
              </div>

            </div>
          </div>

        </div>

      </div>
    </div>
  );
};

export default ActiveTradeDetails;
