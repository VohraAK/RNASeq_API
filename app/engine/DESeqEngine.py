import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from formulaic import Formula
from pydeseq2.dds import DeseqDataSet
from pydeseq2.ds import DeseqStats

class DESeqEngine:
    '''Main class handling Differential Gene Expression analysis'''
    
    def __init__(self, gene_counts_path: str, metadata_path: str):
        self.gene_counts_path = gene_counts_path
        self.metadata_path = metadata_path

        self.counts_df = None
        self.metadata_df = None

        # need someplace to hold the DeseqDataSet object
        self.dds: DeseqDataSet = None

        self.stats = None
        
        # final results table
        self.results_df = None



    def load_data(self, min_count: int = 10):
        '''Loads the counts and metadata dataframes from paths specified on creation of instance.

        :param min_count: Drop genes whose total count across all samples is below this threshold.
                          Reduces memory usage and speeds up fitting. Default is 10.
        :type min_count: int
        '''

        # check if files exist
        if not os.path.exists(self.gene_counts_path):
            raise FileNotFoundError(f"Gene counts file not found: {self.gene_counts_path}")

        if not os.path.exists(self.metadata_path):
            raise FileNotFoundError(f"Metadata file not found: {self.metadata_path}")

        # Read counts in chunks to avoid loading the full file into RAM at once
        chunks = pd.read_csv(self.gene_counts_path, index_col=0, chunksize=5000)
        self.counts_df = pd.concat(chunks)

        self.metadata_df = pd.read_csv(self.metadata_path, index_col=0)

        if self.counts_df.empty:
            raise ValueError("Gene counts dataframe is empty")

        if self.metadata_df.empty:
            raise ValueError("Metadata dataframe is empty")

        # Low-count gene filter (applied before transpose for efficiency — genes are rows here)
        if min_count > 0:
            gene_totals = self.counts_df.sum(axis=1)
            kept = gene_totals >= min_count
            dropped = int((~kept).sum())
            if dropped:
                print(f"Filtered {dropped} low-count genes (total count < {min_count}). "
                      f"{int(kept.sum())} genes retained.")
            self.counts_df = self.counts_df[kept]

        # transpose the counts dataframe (pydeseq2 requires samples x genes)
        self.counts_df = self.counts_df.T

        # Check for duplicate gene names (common issue: Excel converts MARCH1/MARCH2 to dates)
        duplicates = self.counts_df.columns.duplicated()
        if duplicates.any():
            dup_count = duplicates.sum()
            dup_names = self.counts_df.columns[duplicates].unique().tolist()
            print(f"WARNING: Found {dup_count} duplicate gene(s): {dup_names[:5]}{'...' if len(dup_names) > 5 else ''}")
            print(f"Automatically removing duplicates (keeping first occurrence)...")
            self.counts_df = self.counts_df.loc[:, ~duplicates]
            print(f"Fixed. Now have {self.counts_df.shape[1]} unique genes.")

        # Check if counts and metadata have matching samples
        counts_samples = set(self.counts_df.index)
        metadata_samples = set(self.metadata_df.index)

        if not counts_samples == metadata_samples:
            missing_in_meta = counts_samples - metadata_samples
            missing_in_counts = metadata_samples - counts_samples
            raise ValueError(f"Sample mismatch! Missing in meta: {missing_in_meta}.\nMissing in counts: {missing_in_counts}")

        # Reindex metadata to match sample order in counts_df
        self.metadata_df = self.metadata_df.reindex(self.counts_df.index)

        # Integer type check and cast
        if not self.counts_df.values.dtype.kind in 'iu':  # i=signed int, u=unsigned int
            if (self.counts_df.values % 1 != 0).any():
                raise ValueError("DESeq2 requires raw integer counts. Floating point data detected.")
            self.counts_df = self.counts_df.astype(int)

        # Downcast to int32 — halves memory vs int64 for typical RNA-seq count ranges
        self.counts_df = self.counts_df.astype('int32')

        print(f"Data loaded: {self.counts_df.shape[0]} samples x {self.counts_df.shape[1]} genes.")
        print(f"Counts (first 5x5):\n{self.counts_df.iloc[:5, :5]}\n")
        print(f"Metadata:\n{self.metadata_df.head()}\n")



    def analyse(self, design_formula: str, ref_levels: dict, refit_cooks=True):
        '''
        Runs DESeq model on the loaded data.
        
        :param design_formula: Wilkinson formula denoting the model specification for analysis.
        :type design_formula: str
        :param ref_levels: Maps factors to baseline/reference conditions.
        :type ref_levels: dict
        '''
        
        # validate data is loaded
        if self.counts_df is None or self.metadata_df is None:
            raise ValueError("Data not loaded! Run load_data() first.")
        
        # get all the specified factors from the provided design formula
        factors = [str(v) for v in Formula(design_formula).required_variables]

        # recategorise each factor/variable to pass them to dds object
        for factor in factors:
            if factor in ref_levels:
                ref = ref_levels[factor]
                self.metadata_df[factor] = pd.Categorical(self.metadata_df[factor])
                self.metadata_df[factor] = self.metadata_df[factor].cat.reorder_categories(
                    [ref] + [lvl for lvl in self.metadata_df[factor].cat.categories if lvl != ref]
                )

        # instantiate the dds object
        self.dds = DeseqDataSet(
            counts=self.counts_df,
            metadata=self.metadata_df,
            design_factors=factors,
            refit_cooks=refit_cooks
        )

        # fit it
        self.dds.deseq2()



    def get_results(self, contrast_levels: list):
        """Extracts differential expresson results from the fitted DESeq model, according to specified contrast\n
        contrast:\nE.g., ["condition", "B", "A"] means that the condition feature is tested (B vs A)"""

        if self.dds is None:
            raise ValueError("Model not fitted! Run analyse()...")
        
        # init the stats object
        stats = DeseqStats(self.dds, contrast=contrast_levels)
        
        self.stats = stats
        
        # get the summary
        stats.summary()
        
        stats.plot_MA
        
        # store the results as a Pandas DataFrame
        self.results_df = stats.results_df
        
        return self.results_df


    def plot_volcano(self, padj_threshold=0.05, log2fc_threshold=1.0, point_size=10, figsize=(10, 6)):
        """
        Generate volcano plot (log2FoldChange vs -log10(padj)).
        
        :param padj_threshold: Adjusted p-value threshold for significance
        :type padj_threshold: float
        :param log2fc_threshold: Absolute log2 fold change threshold
        :type log2fc_threshold: float
        :param figsize: Figure size (width, height)
        :type figsize: tuple
        :return: matplotlib Figure object
        """
        if self.results_df is None:
            raise ValueError("No results available! Run get_results() first.")
        
        df = self.results_df.copy()
        
        # Handle zero/NaN p-values
        df['padj_safe'] = df['padj'].replace(0, np.nan)
        df['-log10(padj)'] = -np.log10(df['padj_safe'])
        
        # Classify genes
        significant = (df['padj'] < padj_threshold) & (np.abs(df['log2FoldChange']) > log2fc_threshold)
        df['upregulated'] = significant & (df['log2FoldChange'] > log2fc_threshold)
        df['downregulated'] = significant & (df['log2FoldChange'] < -log2fc_threshold)
        
        # Create plot
        fig, ax = plt.subplots(figsize=figsize)
        
        # Non-significant
        non_sig = df[~significant]
        ax.scatter(non_sig['log2FoldChange'], non_sig['-log10(padj)'], 
                   c='gray', alpha=0.5, s=point_size, label='Not significant')
        
        # Downregulated
        down = df[df['downregulated']]
        ax.scatter(down['log2FoldChange'], down['-log10(padj)'], 
                   c='blue', alpha=0.7, s=point_size, label='Downregulated')
        
        # Upregulated
        up = df[df['upregulated']]
        ax.scatter(up['log2FoldChange'], up['-log10(padj)'], 
                   c='red', alpha=0.7, s=point_size, label='Upregulated')
        
        # Threshold lines
        ax.axhline(y=-np.log10(padj_threshold), color='black', 
                   linestyle='--', linewidth=0.8, alpha=0.5)
        ax.axvline(x=log2fc_threshold, color='black', 
                   linestyle='--', linewidth=0.8, alpha=0.5)
        ax.axvline(x=-log2fc_threshold, color='black', 
                   linestyle='--', linewidth=0.8, alpha=0.5)
        
        ax.set_xlabel('Log2 Fold Change', fontsize=12)
        ax.set_ylabel('-Log10(Adjusted P-value)', fontsize=12)
        ax.set_title(f'Volcano Plot (padj < {padj_threshold}, |log2FC| > {log2fc_threshold})', 
                     fontsize=14, fontweight='bold')
        ax.legend(loc='best')
        ax.grid(True, alpha=0.3)
        
        plt.tight_layout()
        return fig


    def ma_plot(self, s=50, **kwargs):
        """
        Generate MA plot using pydeseq2's built-in plot_MA method.
        
        :param s: Point size for scatter plot (default: 50)
        :type s: int or float
        :param kwargs: Additional arguments passed to DeseqStats.plot_MA()
                       (e.g., alpha, log, cmap, etc.)
        :return: matplotlib Figure object
        """
        if self.stats is None:
            raise ValueError("No results available! Run get_results() first.")
        
        self.stats.plot_MA(s=s, **kwargs)
        fig = plt.gcf()
        return fig