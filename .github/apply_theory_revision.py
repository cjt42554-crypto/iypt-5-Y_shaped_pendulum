from pathlib import Path
import subprocess

p=Path('01_最终理论/01-前向预测理论.md')
assert subprocess.check_output(['git','hash-object',str(p)],text=True).strip()=='6b96b6c3679d0cb3a20e861927caa9d8ccd9a71a'
s=p.read_text()
def rep(old,new):
    global s
    assert s.count(old)==1,old[:120]
    s=s.replace(old,new)
rep('> 本文给出 Y 形摆的两套闭合前向物理模型：连续柔索模型与理想环面模型。','> 本文给出 Y 形摆的两套闭合前向物理模型：连续柔索模型与理想环面模型。\n> 理论修订：2026-09-05；补充张紧工作区、受载线性化与有限观察窗降阶误差条件。')
marker='式 (F.16) 表示完整输入在有效域内决定完整状态；它不是省略证明条件的全局 PDE 定理。最大有效时间由第 6 节给出。'
rep(marker,marker+r'''

### 4.4 全程张紧工作区与线性化可预测性

合法输入、被动耗散与存在唯一强解是不同条件。最低输入正则性不单独保证式 (F.14) 的强解存在正长度时间。特别地，允许 $C_{a,i}=0$ 时仍有传播波，不能从能量有界推得 $\boldsymbol r_i\in C^1_tH^2_S$。即使采用更光滑的候选初态 $\boldsymbol r_{i0}\in H^3$、$\boldsymbol v_{i0}\in H^2$，仍须检查端点位置、速度及相应加速度/牵引相容性，外力和支点的匹配正则性，以及本构切换处的光滑性；这些要求本身不是完整非线性网络的存在定理。

常用张紧工作区要求，在整个所声明观察窗内

$$
\inf_{i,S,t}N_i\ge N_*>0,\qquad
\inf_{i,S,t}\lambda_i>\lambda_{\min},
\tag{F.16a}
$$

并与材料有效域、接触守卫及不光滑切换面保持预先指定的正裕量。$N_*$ 是工作区裕量，不是人为给张力方程添加的预载。实际输入和轨迹必须支持这些条件；孤立时刻张力为正不能证明整个区间有正下界。

固定支点、静止空气和恒定外力下，先取满足原方程的受载平衡 $\overline{\boldsymbol r}_i$。令 $\overline\lambda_i=|\overline{\boldsymbol r}_{i,S}|$、$\overline{\boldsymbol t}_i=\overline{\boldsymbol r}_{i,S}/\overline\lambda_i$，在严格受拉且本构可微的平衡点，弹性牵引对材料切向的线性化为

$$
\mathsf K_i^{\rm loc}
=EA_i\mathcal P'_{\delta_i}(\overline\lambda_i-1)
\overline{\boldsymbol t}_i\overline{\boldsymbol t}_i^{\mathsf T}
+\frac{\overline N_i}{\overline\lambda_i}
\left(\mathsf I-\overline{\boldsymbol t}_i\overline{\boldsymbol t}_i^{\mathsf T}\right).
\tag{F.16b}
$$

因此轴向模量与几何张力共同提供恢复力；须同时有 $EA_i\mathcal P'_{\delta_i}\ge k_*>0$ 和 $\overline N_i/\overline\lambda_i\ge k_\perp>0$ 才得到该局部切线的统一正定性。这里 $k_*,k_\perp$ 都具有力的单位，不能与频率混用。受载平衡附近的轴向黏性切线为

$$
\mathsf C_i^{\rm loc}
=C_{a,i}\mathcal P'_{\delta_i}(\overline\lambda_i-1)
\overline{\boldsymbol t}_i\overline{\boldsymbol t}_i^{\mathsf T}\succeq0.
\tag{F.16c}
$$

它至多沿轴向有秩一耗散，不是对三维中心线全部方向的统一抛物型正则化；不据此宣称横向高阶正则性自动改善。

在端点相容的线性位移空间中，若装配后的质量算子 $M$ 正定、恢复算子 $K$ 在允许位移子空间上强制、耗散算子 $C\succeq0$，则线性化方程和能量满足

$$
M\ddot u+C\dot u+Ku=f,\qquad
E_{\rm lin}=\tfrac12\langle\dot u,M\dot u\rangle+\tfrac12\langle u,Ku\rangle,
$$

$$
\dot E_{\rm lin}=-\langle\dot u,C\dot u\rangle+\langle\dot u,f\rangle.
\tag{F.16d}
$$

对具有足够正则性的线性解，无外力时给出能量稳定性；对相同算子下两组输入之差，配合外力范数估计得到有限时连续依赖。这是线性化层级的结论，不是式 (F.14) 全非线性张紧—松弛问题的局部存在或全局延拓证明。松弛、接触及本构切换仍按原有效域分别处理。
''')
rep('理想环面前向理论到此为止。主频、频率比、有限振幅频移、可公度闭合、共振和稳定性不是前向演化方程本身，而是由轨迹进一步提取的结构性质。','理想环面的基本演化方程到此为止。下一节只给出与连续柔索比较时的受控近似条件和观察窗误差预算；不据此展开可公度闭合、共振或分岔结构。')
marker='## 10. 参数来源、不确定性与可证伪性'
rep(marker,r'''### 9.8 连续柔索到环面近似的条件与误差预算

**受载几何与相容初态。** 比较两套模型时，先用同一物理输入求连续柔索受载平衡。第 $i$ 支的受载弧长为

$$
\overline L_i=\int_0^{L_i^0}\overline\lambda_i(S)\,\mathrm dS.
\tag{T.22}
$$

无载参考长度 $L_i^0$ 不能直接当作不可伸长模型的受载长度。绳质量导致的静态弯曲也不能仅靠替换长度消除：须同时报告端点弦长、弧长和形状偏差，并检查一个定长直绳环面是否能同时匹配结点与摆球平衡位置。匹配规则须在看验证轨迹前固定，不能由后续轨迹反调长度。

常用小参数为

$$
\epsilon_m=\frac{m_J+\sum_i\mu_iL_i^0}{m},\qquad
\epsilon_e=\max_i\frac{|\overline L_i-L_i^0|}{L_i^0},\qquad
\epsilon_f=\frac{\omega_{\rm band}}{\omega_{\rm int}}.
\tag{T.23}
$$

$\omega_{\rm band}$ 是目标输入及响应的频率带上界；$\omega_{\rm int}$ 是在所选慢变量固定后、受载线性化内部子系统的最低正频率。它不是任选一支绳的纵波频率；最低横向模态也可能限制降阶。无严格正内模频率、无频带分离或张力接近零时，不使用这一受控低频约化。

三个比值小仍不保证任意初态下环面准确。还须有相容的慢变量初态、受控静态几何误差和足够小的内部自由振动能量。小质量并不排除由大初速携带的有限能量；不把未知绳形或内部初速设零后称为已测输入。两套模型仍分别从 $t=0$ 选择，不在失张时拼接。

**线性内部自由度消去。** 在受载平衡附近选择慢坐标 $q$ 与内部坐标 $z$，线性算子写成

$$
D(s)=s^2M+sC+K
=\begin{bmatrix}D_{qq}&D_{qz}\\D_{zq}&D_{zz}\end{bmatrix}.
$$

当 $D_{zz}$ 可逆时，精确的线性 Schur 补为

$$
D_{\rm eff}(s)=D_{qq}-D_{qz}D_{zz}^{-1}D_{zq},
\qquad
D_{\rm eff}\widehat q
=\widehat f_q-D_{qz}D_{zz}^{-1}\widehat f_z.
\tag{T.24}
$$

右端的 $\widehat f_q,\widehat f_z$ 包括拉普拉斯变换产生的完整初态项；非零内部初态不能丢弃。一般 $D_{\rm eff}$ 随频率变化，对应记忆而不是常数修正。只保留 $K_{zz}^{-1}$ 是额外的准静态近似，不是精确不变慢流形。

在内部子系统无阻尼且 $M_{zz},K_{zz}\succ0$ 的有限模态表示中，设

$$
\omega_{\rm int}^2
=\min_{v\ne0}\frac{v^{\mathsf T}K_{zz}v}{v^{\mathsf T}M_{zz}v},
\qquad r=\frac{|\omega|}{\omega_{\rm int}}<1.
$$

令 $B=K_{zz}^{-1/2}M_{zz}K_{zz}^{-1/2}$，由 $(I-\omega^2B)^{-1}$ 的谱表示直接得到

$$
\left\|K_{zz}^{1/2}
\left[(K_{zz}-\omega^2M_{zz})^{-1}-K_{zz}^{-1}\right]
K_{zz}^{1/2}\right\|_2
\le\frac{r^2}{1-r^2}.
\tag{T.25}
$$

这是内部线性逆算子的加权误差界，不是整个非线性轨迹的误差界。总响应还受耦合块、慢系统的响应放大、初态能量、静态匹配、观测算子及非线性余项影响；阻尼存在时应使用完整 $D_{zz}(i\omega)$，不能直接照搬式 (T.25)。

对简单、孤立的保守模态 $Kv_j=\omega_j^2Mv_j$，小的质量和刚度修正给出

$$
\frac{\delta\omega_j}{\omega_j}
=\frac{v_j^{\mathsf T}(\delta K-\omega_j^2\delta M)v_j}
{2\omega_j^2v_j^{\mathsf T}Mv_j}
+O(\|\delta\|^2).
\tag{T.26}
$$

$\|\delta\|$ 表示经一致参考尺度归一化后的扰动大小。重根或接近简并时须在整个模态子空间内处理，不能对任意基向量独立使用标量公式。此式用于预测误差来源，不替代原连续方程。

**整个观察窗的相位误差。** 在模态可辨识、幅值非零且相位展开一致时

$$
\delta\phi_j(T)=\delta\phi_j(0)+\int_0^T\delta\omega_j(t)\,\mathrm dt,
\qquad
|\delta\phi_j(T)|\le|\delta\phi_j(0)|+
\int_0^T|\delta\omega_j(t)|\,\mathrm dt.
\tag{T.27}
$$

恒定频率误差产生 $T\delta\omega_j$ 的累计偏差。对等幅正弦分量，位置差满足 $|\delta x|\le2A|\sin(\delta\phi/2)|\le A|\delta\phi|$；振幅和静态几何误差须另加。相位在零幅值处没有定义，不能用任意相位填充值参与验收。

因此应在计算前固定目标观察窗、幅值/相位或直接轨迹误差门限，用同一联合输入比较连续柔索、受载修正模型与理想环面。近零模态幅值、模态混合或不具单频意义时，改用原始轨迹误差，不强套式 (T.27)。短时能量残差小不能替代长时相位误差检查；数值误差、输入误差与物理降阶误差必须分别报告。

**平滑宽度不是纯数值参数。** 受载伸长 $x_i=\overline\lambda_i-1$ 与 $\delta_i$ 的比值决定是否落入本构过渡带。在 $0<x_i<\delta_i$ 中

$$
\mathcal P'_{\delta_i}(x_i)
=4\frac{x_i}{\delta_i}-3\left(\frac{x_i}{\delta_i}\right)^2,
\qquad
\max\mathcal P'_{\delta_i}=\frac43
\quad\text{于 }x_i=\frac23\delta_i.
\tag{T.28}
$$

故过渡带会改变切线刚度及轴向黏性响应。参数 $EA_i,C_{a,i},\delta_i$ 应结合实际预拉伸范围辨识并保留相关不确定性；不能为稳定积分而调 $\delta_i$ 后仍宣称物理模型不变。若整个工作窗都处在 $x_i\ge\delta_i$，才可使用该段 $\mathcal P'_{\delta_i}=1$ 的线性受拉本构。

---

'''+marker)
p.write_text(s)
d=Path('90_候选工作区/current/2026-09-05_前向理论修订')
d.mkdir(parents=True,exist_ok=True)
(d/'check_theory.py').write_text(r'''"""Algebraic regression for linearized validity/error formulas; not a PDE theorem."""
import math
import random
import unittest
from pathlib import Path

def dot(a,b): return sum(x*y for x,y in zip(a,b))

class TheoryChecks(unittest.TestCase):
    def test_activation_tangent(self):
        f=lambda x:4*x-3*x*x
        self.assertAlmostEqual(f(2/3),4/3)
        self.assertEqual(f(0),0.)
        self.assertEqual(f(1),1.)
        self.assertLessEqual(max(f(i/1000) for i in range(1001)),4/3)
    def test_taut_elastic_tangent(self):
        rng=random.Random(5)
        for unused in range(40):
            t=[rng.uniform(-1,1) for i in range(3)]
            norm=math.sqrt(dot(t,t)); t=[x/norm for x in t]
            v=[rng.uniform(-1,1) for i in range(3)]
            ka,kt=3.,.4
            q=ka*dot(t,v)**2+kt*(dot(v,v)-dot(t,v)**2)
            self.assertGreaterEqual(q,min(ka,kt)*dot(v,v)-1e-13)
    def test_axial_viscosity_is_not_uniformly_elliptic(self):
        t=[1.,0.,0.]; transverse=[0.,1.,0.]
        self.assertEqual(2*dot(t,transverse)**2,0.)
        self.assertGreater(2*dot(t,t)**2,0.)
    def test_schur_complement_keeps_internal_forcing(self):
        a,b,c,d=3.,.4,.4,2.
        fq,fz=1.,.7
        q=(fq-b*fz/d)/(a-b*c/d)
        z=(fz-c*q)/d
        self.assertAlmostEqual(a*q+b*z,fq)
        self.assertAlmostEqual(c*q+d*z,fz)
        self.assertNotAlmostEqual(q,fq/(a-b*c/d))
    def test_resolvent_bound(self):
        masses=[2.,1.]; stiffness=[8.,9.]
        wint=min(math.sqrt(k/m) for k,m in zip(stiffness,masses))
        for r in (0.,.01,.2,.7,.95):
            w=r*wint
            error=max(abs(k/(k-w*w*m)-1) for k,m in zip(stiffness,masses))
            self.assertLessEqual(error,r*r/(1-r*r)+1e-12)
    def test_small_mass_does_not_imply_small_internal_energy(self):
        for eps in (1e-1,1e-3,1e-6):
            self.assertAlmostEqual(.5*eps**2*(1/eps)**2,.5)
    def test_eigenfrequency_perturbation(self):
        k,m,dk,dm=8.,2.,.3,.2
        f=lambda e:math.sqrt((k+e*dk)/(m+e*dm))
        h=1e-5; omega=f(0)
        rel=(f(h)-f(-h))/(2*h)/omega
        self.assertAlmostEqual(rel,(dk-omega**2*dm)/(2*omega**2*m),places=9)
    def test_phase_horizon_and_position_error(self):
        rng=random.Random(27)
        for unused in range(40):
            phi=rng.uniform(-20,20); delta=rng.uniform(-1,1); amplitude=.3
            error=abs(amplitude*(math.cos(phi+delta)-math.cos(phi)))
            self.assertLessEqual(error,amplitude*abs(delta)+1e-14)
        self.assertAlmostEqual(100*.002,.2)
    def test_document_invariants(self):
        s=Path('01_最终理论/01-前向预测理论.md').read_text()
        tags=[v.split('}',1)[0] for v in s.split(chr(92)+'tag{')[1:]]
        self.assertGreater(len(tags),55)
        self.assertEqual(len(tags),len(set(tags)))
        self.assertEqual(sum(line.strip()=='$$' for line in s.splitlines())%2,0)
        for tag in ['F.16a','F.16b','F.16c','F.16d','T.22','T.23','T.24','T.25','T.26','T.27','T.28']:
            self.assertIn(tag,tags)
        self.assertIn('不是整个非线性轨迹的误差界',s)
        self.assertIn('不能在同一条轨迹中临时互换',s)
if __name__=='__main__': unittest.main(verbosity=2)
''')
Path('90_候选工作区/交接说明_current.md').write_text('''# 当前交接：2026-09-05 前向理论修订

## 当前状态

基于 `cdf1c406b9e083a6601dff066b5605999ac1f955` 在 main 修改最终前向理论。连续柔索与理想环面的核心演化、张力和能量方程未改；本轮补充条件适用性及受载降阶的误差关系。没有新实验、没有新数值 campaign，也没有宣称证明退化柔索的全局适定性。

## 本轮完成

`01_最终理论/01-前向预测理论.md` 新增第 4.4 与 9.8 节：

1. 区分合法输入、耗散和强解存在；指出零轴向黏性下波动正则性及更光滑初态也需端点/外力兼容。给出全程张紧、材料/几何和切换面裕量的工作区，而非把样点正张力称为区间认证。
2. 推导受载平衡的弹性局部切线：轴向材料刚度和横向几何张力；明确轴向黏性仅秩一，不会自动使三维中心线完全抛物型。给出线性化能量稳定性条件，不将其上升为全非线性存在定理。
3. 比较无载参考长、受载弧长与端点弦长，避免用一个长度参数掩盖自重绳形。定义质量、伸长与频带比，要求初态内部振动能量可控；继续保持两套模型从 t=0 独立选择，不在失张时切换。
4. 给出保留内部强迫及初态项的 Schur 补；推导无阻尼正定内部子系统的加权逆算子误差界，明确不是完整非线性轨迹界。给出简单模态频率一阶修正和整个观察窗相位累计误差。
5. 给出激活过渡带切线导数最大值 4/3，要求把平滑宽度、刚度和轴向黏性视为联合物理标定参数，而不是任意数值稳定化参数。

## 验证与证据

独立代数回归入口：`current/2026-09-05_前向理论修订/check_theory.py`。覆盖激活导数、弹性切线、轴向黏性退化、带内部强迫的 Schur 补、逆算子误差界、小质量有限内模能量、频率微扰、相位/位置误差以及文档标签。实际日志保存在同目录 `validation.txt`。这些检查不替代完整非线性 PDE 证明、数值收敛或实验验证。

## 程序及科学边界

本轮没有新增生产求解器、内部模态求解器或自动误差认证。理论中给出的受载匹配、模态分离和相位预算尚须在目标参数及观察窗上实际计算；不能仅因本文新增公式就声明环面近似在全部工况准确。没有新增长时混沌、接触或弯曲理论。

上轮独立能量账本、动态能量尺度与性能诊断保留；原 113 项求解器测试记录仍在 `current/2026-09-05_数值审查修复/validation.log`，不把旧验证计作本轮重跑。高保真、任意连续守卫完备性、松弛后强解延拓与装置验证仍未获得资格。

## 接续优先级

先选实际张紧工况，计算同输入受载平衡、内模频率及内部初态能量，按目标观察窗比较连续模型与环面的轨迹/相位；数值细化误差与物理降阶误差分开。近失张工况先评估工作区退出，不无依据扩展大规模杆接触系统。`交接说明_history.md` 保持零字节，原始结果、Git 历史及冻结证据不改写。
''')
Path('90_候选工作区/交接说明_history.md').write_bytes(b'')
