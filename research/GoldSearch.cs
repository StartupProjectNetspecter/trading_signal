// Fast isolated research engine. No MT5, network, orders or messaging APIs.
using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using System.Globalization;

class GoldSearch {
    public struct Setup { public int I,D,Order,Expiry,Window,Flags; public double Entry,Stop,Q1,Q2; }
    public class Data {
        public int N,Months,Folds;
        public long[] T;
        public double[][] V;
        public int[][] K;
        public Setup[][] Sources;
        public Data(string path) {
            using(var r=new BinaryReader(File.OpenRead(path))) {
                if(r.ReadInt32()!=20261015) throw new Exception("Invalid data format");
                N=r.ReadInt32(); Months=r.ReadInt32(); Folds=r.ReadInt32();
                T=new long[N]; for(int i=0;i<N;i++) T[i]=r.ReadInt64();
                V=new double[9][];
                for(int k=0;k<9;k++) { V[k]=new double[N]; for(int i=0;i<N;i++) V[k][i]=r.ReadDouble(); }
                // minute, day, weekday, news, H1 BOS, H1 HHHL, M15 BOS, M15 HHHL, fold, month
                K=new int[10][];
                for(int k=0;k<10;k++) { K[k]=new int[N]; for(int i=0;i<N;i++) K[k][i]=r.ReadInt32(); }
                int ns=r.ReadInt32(); Sources=new Setup[ns][];
                for(int s=0;s<ns;s++) {
                    int count=r.ReadInt32(); Sources[s]=new Setup[count];
                    for(int i=0;i<count;i++) {
                        Setup a=new Setup(); a.I=r.ReadInt32(); a.D=r.ReadInt32(); a.Entry=r.ReadDouble();
                        a.Stop=r.ReadDouble(); a.Order=r.ReadInt32(); a.Expiry=r.ReadInt32(); a.Window=r.ReadInt32();
                        a.Q1=r.ReadDouble(); a.Q2=r.ReadDouble(); a.Flags=r.ReadInt32(); Sources[s][i]=a;
                    }
                }
                if(r.BaseStream.Position!=r.BaseStream.Length) throw new Exception("Trailing binary data");
            }
        }
    }
    public class P {
        public int Id,Source,Bias,Start,End,Cap,Cooldown,StopMode,Expiry,Hold,Management,Direction,Flags;
        public double Buffer,RR,MinRisk,MaxRisk,ADXMin,ADXMax,Body,VolMin,VolMax,Q1,Q2;
        public static P Parse(string line) {
            string[] x=line.Split(','); int j=0; P p=new P();
            p.Id=int.Parse(x[j++]); p.Source=int.Parse(x[j++]); p.Bias=int.Parse(x[j++]);
            p.Start=int.Parse(x[j++]); p.End=int.Parse(x[j++]); p.Cap=int.Parse(x[j++]);
            p.Cooldown=int.Parse(x[j++]); p.StopMode=int.Parse(x[j++]);
            p.Buffer=double.Parse(x[j++]); p.RR=double.Parse(x[j++]); p.MinRisk=double.Parse(x[j++]);
            p.MaxRisk=double.Parse(x[j++]); p.Expiry=int.Parse(x[j++]); p.Hold=int.Parse(x[j++]);
            p.Management=int.Parse(x[j++]); p.Direction=int.Parse(x[j++]);
            p.ADXMin=double.Parse(x[j++]); p.ADXMax=double.Parse(x[j++]); p.Body=double.Parse(x[j++]);
            p.VolMin=double.Parse(x[j++]); p.VolMax=double.Parse(x[j++]);
            p.Q1=double.Parse(x[j++]); p.Q2=double.Parse(x[j++]); p.Flags=int.Parse(x[j++]);
            if(j!=x.Length || p.RR<=0 || p.Buffer<0 || p.Cap<1 || p.Hold<1 || p.Start>=p.End)
                throw new Exception("Invalid configuration");
            return p;
        }
    }
    public class S {
        public int N,W,Signals,Purged; public double Sum,Pos,Neg,Sq,Cum,Peak,DD;
        public HashSet<int> SignalDays=new HashSet<int>(),FillDays=new HashSet<int>();
        public void Add(double r,int day) {
            N++; if(r>0) { W++; Pos+=r; } else Neg-=r;
            Sum+=r; Sq+=r*r; Cum+=r; Peak=Math.Max(Peak,Cum); DD=Math.Max(DD,Peak-Cum); FillDays.Add(day);
        }
        public string Csv() {return string.Join(",",new double[]{N,W,Sum,Pos,Neg,Sq,DD,Signals,SignalDays.Count,FillDays.Count,Purged}.Select(x=>x.ToString("R")));}
    }
    static int Lower(long[] x,long t) { int lo=0,hi=x.Length; while(lo<hi) {int m=(lo+hi)/2; if(x[m]<t)lo=m+1;else hi=m;}return lo; }
    static double Round(double x) {return Math.Round(x,2,MidpointRounding.ToEven);}
    public static string Sim(Data a,P p,double spread,double slip,double fee,StreamWriter detail) {
        var stats=Enumerable.Range(0,a.Folds).Select(x=>new S()).ToArray();
        double[] monthly=new double[a.Months];
        int last=-100000,lastDay=-1,count=0; long free=long.MinValue;
        HashSet<long> windows=new HashSet<long>();
        double[] o=a.V[0],h=a.V[1],l=a.V[2],c=a.V[3],atr=a.V[4],adx=a.V[6],body=a.V[7],vol=a.V[8];
        int[] minute=a.K[0],day=a.K[1],wd=a.K[2],news=a.K[3],fold=a.K[8],month=a.K[9];
        foreach(Setup row in a.Sources[p.Source]) {
            int i=row.I,d=row.D;
            if(wd[i]>=5 || news[i]!=0 || minute[i]<p.Start || minute[i]>=p.End || i-last<p.Cooldown)continue;
            if(p.Direction!=0 && p.Direction!=d)continue;
            if(p.Bias>0 && a.K[p.Bias+3][i]!=d)continue;
            if(!Finite(adx[i]) || !Finite(vol[i]) || adx[i]<p.ADXMin || adx[i]>p.ADXMax || body[i]<p.Body || vol[i]<p.VolMin || vol[i]>p.VolMax)continue;
            if(row.Q1<p.Q1 || row.Q2<p.Q2 || (row.Flags&p.Flags)!=p.Flags)continue;
            if(day[i]!=lastDay) { lastDay=day[i];count=0; }
            if(count>=p.Cap)continue;
            long window=((long)day[i])*10000+row.Window;
            if(row.Window>=0 && windows.Contains(window))continue;
            double entry=Round(row.Entry);
            double stop=Round((p.StopMode==0?row.Stop:entry-d*p.StopMode*atr[i]/2)-d*p.Buffer*atr[i]);
            double planned=(entry-stop)*d;
            if(!Finite(planned) || !Finite(atr[i]) || planned<p.MinRisk || planned>p.MaxRisk*atr[i])continue;
            double target=Round(entry+d*p.RR*planned);
            if((target-entry)*d<=0)continue;
            last=i; count++; if(row.Window>=0) windows.Add(window);
            int f=fold[i]; stats[f].Signals++;stats[f].SignalDays.Add(day[i]);
            long signal=a.T[i]+300;
            if(signal<free) { if(detail!=null) Detail(detail,p.Id,i,d,entry,stop,target,-1,0,-1,0,0,"capacity",f);continue; }
            int start=Lower(a.T,signal),fill=-1,exit=-1;
            long expiry=signal+300*(row.Order==0?1:(p.Expiry==0?row.Expiry:p.Expiry));
            string outcome="expired"; double px=0,ex=0,risk=0;
            for(int j=start;j<a.N && a.T[j]<expiry;j++) {
                if(news[j]!=0) {outcome="news_cancel";free=a.T[j]+300;break;}
                double closeOpen=o[j]+(d==-1?spread:0);
                if((closeOpen-stop)*d<=0 || (closeOpen-target)*d>=0) {outcome="invalid_gap";free=a.T[j]+300;break;}
                if(row.Order==0) {fill=j;px=o[j]+(d==1?spread+slip:-slip);}
                else if(d==1?l[j]+spread<=entry:h[j]>=entry) {fill=j;px=entry;}
                if(fill>=0) {
                    risk=(px-stop)*d;
                    if(risk<=0 || (target-px)*d<=0) {fill=-1;outcome="invalid_fill";free=a.T[j]+300;}
                    break;
                }
                if(d==1?h[j]>=target:l[j]+spread<=target) {outcome="cancelled";free=a.T[j]+300;break;}
            }
            if(fill<0) {
                if(outcome=="expired") free=expiry;
                if(detail!=null)Detail(detail,p.Id,i,d,entry,stop,target,-1,0,-1,0,0,outcome,f);
                continue;
            }
            long deadline=a.T[fill]+p.Hold*3600;
            int max=Lower(a.T,deadline)-1; max=Math.Min(max,a.N-1);
            // Never close retrospectively before a missing-data deadline: use first available open.
            double activeStop=stop,size=1,banked=0; bool partial=false;
            outcome="time";
            for(int j=fill;j<=max;j++) {
                double lo=l[j]+(d==-1?spread:0),hi=h[j]+(d==-1?spread:0),op=o[j]+(d==-1?spread:0);
                if(d==1?lo<=activeStop:hi>=activeStop) {
                    exit=j; ex=(d==1?Math.Min(activeStop,op):Math.Max(activeStop,op))-d*slip;
                    outcome=activeStop==stop?"sl":"be";break;
                }
                if(j==fill)continue;
                double best=d==1?hi:lo;
                // Partial and BE at +1R only when that threshold is BELOW the planned target.
                double one=px+d*risk;
                if(p.Management==2 && !partial && (target-one)*d>0 && (best-one)*d>=0) {
                    size=0.5;banked=0.5*risk;partial=true;
                }
                if((best-target)*d>=0) {exit=j;ex=target;outcome="tp";break;}
                if(p.Management>0 && (target-one)*d>0 && (best-one)*d>=0)activeStop=px;
            }
            if(exit<0) {
                int next=max+1;
                if(next<a.N && a.T[next]>deadline && a.T[max]+300<deadline) {
                    exit=next;ex=o[next]+(d==-1?spread:0)-d*slip;outcome="time_gap";
                } else {
                    exit=max;ex=c[max]+(d==-1?spread:0)-d*slip;
                    if(max==a.N-1 && a.T[max]+300<deadline)outcome="end_censored";
                }
            }
            free=a.T[exit]+300;
            double r=(banked+size*(ex-px)*d-fee)/risk;
            if(partial)outcome+="+partial";
            if(fold[exit]!=f || outcome.StartsWith("end_censored"))stats[f].Purged++;
            else {stats[f].Add(r,day[fill]);monthly[month[exit]]+=r;}
            if(detail!=null)Detail(detail,p.Id,i,d,entry,stop,target,fill,px,exit,ex,r,outcome,f);
        }
        return p.Id+","+string.Join(",",stats.Select(s=>s.Csv()))+","+string.Join(",",monthly.Select(x=>x.ToString("R")));
    }
    static bool Finite(double x) {return !double.IsNaN(x)&&!double.IsInfinity(x);}
    static void Detail(StreamWriter w,int id,int i,int d,double entry,double stop,double tp,int fill,double px,int exit,double ex,double r,string outcome,int fold) {
        w.WriteLine(string.Join(",",new object[]{id,i,d,entry.ToString("R"),stop.ToString("R"),tp.ToString("R"),fill,px.ToString("R"),exit,ex.ToString("R"),r.ToString("R"),outcome,fold}));
    }
    public static void Main(string[] args) {
        CultureInfo.CurrentCulture=CultureInfo.InvariantCulture;
        var a=new Data(args[0]);
        double spread=double.Parse(args[3]),slip=double.Parse(args[4]),fee=double.Parse(args[5]);
        using(var output=new StreamWriter(args[2])) {
            string header="id";
            for(int f=0;f<a.Folds;f++) foreach(string key in new string[]{"n","wins","sum","positive","negative","sq","dd","signals","signal_days","fill_days","purged"})header+=",f"+f+"_"+key;
            for(int m=0;m<a.Months;m++)header+=",month_"+m;
            output.WriteLine(header);
            var lines=File.ReadAllLines(args[1]);
            for(int k=1;k<lines.Length;k++) {
                P p=P.Parse(lines[k]); StreamWriter detail=null;
                if(args.Length>6) {detail=new StreamWriter(args[6]+"_"+p.Id+".csv");detail.WriteLine("id,signal_i,d,entry,sl,tp,fill_i,fill_price,exit_i,exit_price,r,outcome,fold");}
                output.WriteLine(Sim(a,p,spread,slip,fee,detail));
                if(detail!=null)detail.Dispose();
                if(k%250==0 || k==lines.Length-1) {output.Flush();Console.WriteLine(k+"/"+(lines.Length-1)+" completed");}
            }
        }
    }
}
